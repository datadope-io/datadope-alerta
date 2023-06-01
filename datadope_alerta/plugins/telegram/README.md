Telegram Plugin
============================
This plugin enables users to send messages via Telegram using an API provided by Telegram.

### Utility of the Plugin
With this plugin, you can send messages via Telegram to specific individuals or groups. This plugin will send a different message depending on the severity of the alert. 

### Plugin Configuration
To use this plugin, you will need to create a Telegram bot and obtain an API token. Once you have created a bot, you will be given an API token that you will need to use to authenticate your requests. Also, you will need to add the bot to a public channel, then the bot will be able to send messages to that group or chat.

#### Steps to Get the Token
Create a Telegram bot by following the instructions provided in the Telegram documentation.
Once you have created the bot, you will be given an API token.
Copy the API token and paste it into the plugin configuration.


#### URL and Token
The URL for the Telegram API is https://api.telegram.org/bot<TOKEN>/sendMessage, where <TOKEN> is the API token for your bot.

### Tags
The following are the tags used in the configuration for this plugin:

#### TELEGRAM_CHATS
This tag is used to specify the chat or chats that you want to send messages to. It is a string that simulates a list, but each element is separated by commas. You can specify one or more chats using their chat IDs. To specify the chat id you have to write "@ + the chat id". For example, if you want to send a message to a chat with the id 123456789, you have to write "@123456789" in the TELEGRAM_CHATS tag.

#### TELEGRAM_SOUND
This tag is used to specify the sound that should be played when the message is received. It is an optional tag, and if not specified, no sound will be played.

#### TELEGRAM_TOKEN
Token of the bot to use to send messages. It can be omitted if TELEGRAM_BOT is provided.

#### TELEGRAM_BOT
This tag is used to specify the name of the bot that you want to use. 
The plugin will search for the token of the bot in the config.yml file. 
If TELEGRAM_TOKEN is provided, this tag has no effect.

### Example
The following is an example of the configuration file for this plugin:

```
bots:
  Datadope_bot:
    token: 'the_token'
max_message_characters: 4000
message_send_timeout_s: 10
url: https://api.telegram.org/bot%s/sendMessage
```

To use this configuration, two options for alert tags can be used:
`TELEGRAM_TOKEN: the_token` or `TELEGRAM_BOT: Datadope_bot`. 
Both options have the same effect.
