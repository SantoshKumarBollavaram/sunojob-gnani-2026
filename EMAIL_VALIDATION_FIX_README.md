# Email validation fix

Apply over the installed SunoJob Email Delivery checkpoint.

This update names missing or invalid email fields, trims surrounding spaces, and displays email progress and errors beside the email controls. Preview does not send messages. Sending still requires reviewing the preview, checking the checkbox and explicitly pressing Send to both now.

Stop the server, back up the four existing files listed below, and extract this archive into ~/sunojob. Run the existing unittest suite, restart with --email, then hard-refresh the page with Ctrl+Shift+R.

Changed files:
- sunojob/webapp.py
- sunojob/static/app.js
- sunojob/static/index.html
- tests/test_email_delivery.py

Verification: 186 offline Python tests pass. JavaScript handler checks cover blank and invalid recipients, whitespace trimming, preview creation, and explicit send gating. No live SMTP connection or email submission was made during verification. Browser visual and live SMTP checks remain to be performed on the user's laptop.

Retry Preview direct email after filling both recipient addresses. Any new error should now identify the field or failure. Do not share credentials in screenshots or chat.
