import asyncio

from sqlalchemy.exc import IntegrityError

from app import notification
from app.db import AsyncSession
from app.db.crud.admin import (
    AdminsSortingOptions,
    create_admin,
    get_admins,
    get_admins_count,
    remove_admin,
    reset_admin_usage,
    update_admin,
)
from app.db.crud.bulk import activate_all_disabled_users, disable_all_active_users
from app.db.crud.user import get_users
from app.db.models import Admin as DBAdmin
from app.models.admin import AdminCreate, AdminDetails, AdminModify
from app.models.group import BulkGroup
from app.node import node_manager
from app.operation import BaseOperation, OperatorType
from app.utils.logger import get_logger

logger = get_logger("admin-operation")


class AdminOperation(BaseOperation):
    async def create_admin(self, db: AsyncSession, new_admin: AdminCreate, admin: AdminDetails) -> AdminDetails:
        """Create a new admin if the current admin has sudo privileges."""
        try:
            db_admin = await create_admin(db, new_admin)
        except IntegrityError:
            await self.raise_error(message="Admin already exists", code=409, db=db)

        if self.operator_type != OperatorType.CLI:
            logger.info(f'New admin "{db_admin.username}" with id "{db_admin.id}" added by admin "{admin.username}"')
        new_admin = AdminDetails.model_validate(db_admin)
        asyncio.create_task(notification.create_admin(new_admin, admin.username))

        return db_admin

    async def modify_admin(
        self, db: AsyncSession, username: str, modified_admin: AdminModify, current_admin: AdminDetails
    ) -> AdminDetails:
        """Modify an existing admin's details."""
        db_admin = await self.get_validated_admin(db, username=username)
        if self.operator_type != OperatorType.CLI and db_admin.is_sudo:
            await self.raise_error(
                message="You're not allowed to modify another sudoer's account. Use pasarguard-cli instead.", code=403
            )

        db_admin = await update_admin(db, db_admin, modified_admin)

        if self.operator_type != OperatorType.CLI:
            logger.info(
                f'Admin "{db_admin.username}" with id "{db_admin.id}" modified by admin "{current_admin.username}"'
            )

        modified_admin = AdminDetails.model_validate(db_admin)
        asyncio.create_task(notification.modify_admin(modified_admin, current_admin.username))
        return modified_admin

    async def remove_admin(self, db: AsyncSession, username: str, current_admin: AdminDetails | None = None):
        """Remove an admin from the database."""
        db_admin = await self.get_validated_admin(db, username=username)
        if self.operator_type != OperatorType.CLI and db_admin.is_sudo:
            await self.raise_error(
                message="You're not allowed to remove sudoer's account. Use pasarguard-cli instead.", code=403
            )

        await remove_admin(db, db_admin)
        if self.operator_type != OperatorType.CLI:
            logger.info(
                f'Admin "{db_admin.username}" with id "{db_admin.id}" deleted by admin "{current_admin.username}"'
            )
            asyncio.create_task(notification.remove_admin(username, current_admin.username))

    async def get_admins(
        self,
        db: AsyncSession,
        username: str | None = None,
        offset: int | None = None,
        limit: int | None = None,
        sort: str | None = None,
    ) -> list[DBAdmin]:
        sort_list = []
        if sort is not None:
            opts = sort.strip(",").split(",")
            for opt in opts:
                try:
                    enum_member = AdminsSortingOptions[opt]
                    sort_list.append(enum_member.value)
                except KeyError:
                    await self.raise_error(message=f'"{opt}" is not a valid sort option', code=400)

        return await get_admins(db, offset, limit, username, sort_list if sort_list else None)

    async def get_admins_count(self, db: AsyncSession) -> int:
        return await get_admins_count(db)

    async def disable_all_active_users(
        self, db: AsyncSession, username: str, admin: AdminDetails, offset: int | None = None
    ):
        """Disable all active users under a specific admin"""
        db_admin = await self.get_validated_admin(db, username=username)

        if db_admin.is_sudo:
            await self.raise_error(message="You're not allowed to disable sudo admin users.", code=403)

        await disable_all_active_users(db=db, admin=db_admin, offset=offset)

        users = await get_users(db, admin=db_admin)
        await node_manager.update_users(users)

        logger.info(f'Admin "{username}" users has been disabled by admin "{admin.username}"')

    async def activate_all_disabled_users(
        self, db: AsyncSession, username: str, admin: AdminDetails, limit: int | None = None
    ):
        """Enable all active users under a specific admin"""
        db_admin = await self.get_validated_admin(db, username=username)

        if db_admin.is_sudo:
            await self.raise_error(message="You're not allowed to enable sudo admin users.", code=403)

        await activate_all_disabled_users(db=db, admin=db_admin, limit=limit)

        users = await get_users(db, admin=db_admin)
        await node_manager.update_users(users)

        logger.info(f'Admin "{username}" users has been activated by admin "{admin.username}"')

    async def reset_admin_usage(self, db: AsyncSession, username: str, admin: AdminDetails) -> AdminDetails:
        db_admin = await self.get_validated_admin(db, username=username)

        db_admin = await reset_admin_usage(db, db_admin=db_admin)
        if self.operator_type != OperatorType.CLI:
            logger.info(f'Admin "{username}" usage has been reset by admin "{admin.username}"')

        reseted_admin = AdminDetails.model_validate(db_admin)
        asyncio.create_task(notification.admin_usage_reset(reseted_admin, admin.username))

        return reseted_admin

    async def sync_admin_groups(
        self, db: AsyncSession, username: str, groups: list[int], users_limit: int, admin: AdminDetails
    ) -> AdminDetails:
        db_admin = await self.get_validated_admin(db, username=username)
        from app.operation.group import GroupOperation

        group_operator = GroupOperation(operator_type=self.operator_type)
        all_groups = await group_operator.get_all_groups(db)
        await group_operator.bulk_remove_groups(
            db,
            BulkGroup(
                group_ids=[group.id for group in all_groups.groups if group.id not in groups],
                users=[user.id for user in db_admin.users],
            ),
            db_admin,
            users_limit,
        )
