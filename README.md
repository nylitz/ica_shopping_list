# ICA Shopping List
Home Assistant integration to ICA shopping list.
This is a fork from [kayjei/ica_shopping_list](https://github.com/kayjei/ica_shopping_list).

## Installation
You need to manually add this custom component to Home Assistant.

Create a new folder inside your Home Assistant installation with the following full path `config/custom_components/ica_shopping_list/`. You have to use this exact naming, otherwise it will not work.

Download the code and place it in your newly created folder.

Restart Home Assistant.

## Remark
You need to have a valid ICA account and a password (6 digits)

## Configuration
Add in configuration.yaml:

```
ica_shopping_list:
  username: ICA-USERNAME
  listname: My shopping list 
  password: ICA PASSWORD
```

`listname`: Case sensitive name of your shopping list inside your ICA account. If the list is not found in your account, it will be created. Blankspace and å, ä, ö are valid characters.
