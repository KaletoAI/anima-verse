---
name: SendMessage
action_hint: Character writes a remote text message to another character NOT in the same room (use this to proactively reach out). Text only — to send along a photo from this turn use JSON {"to": ..., "message": ..., "attach_image": true}; never write '[image attached]' as text
---
Send a remote text message to another character. Use this to proactively reach out (e.g. share important news, ask a question, react to something you observed). The message lands in the recipient's chat. For in-person conversation in the same room use TalkTo.
