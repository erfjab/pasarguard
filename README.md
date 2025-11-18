# Project Description  

This version of PasarGuard has been customized for the MoreBot sales bot.  

## Setup Instructions  

After installing the original version of PasarGuard and making any desired changes, to use this version, replace your PasarGuard tag in the configuration:  

From:  
```  
services:  
  pasarguard:  
    image: pasarguard/panel:latest
```  

To:  
```  
services:  
  pasarguard:  
    image: ghcr.io/erfjab/pasarguard:main  
```  

Then, add these two values to your `.env` file:  

```  
MOREBOT_SECRET=""  # Secret key received from MoreBot (Server Info section)  
MOREBOT_LICENSE="" # License key provided by the admin (@ErfJab)  
```  

Finally, update and restart PasarGuard. Done.