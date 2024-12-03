#smtp_server = 'email-smtp.eu-west-1.amazonaws.com'  # Replace with your region
#smtp_port = 465  # SSL port
#sender_email = 'rego@regomeszaros.awsapps.com'

import boto3
import os

def lambda_handler(event, context):
    # Initialize the SES client
    ses_client = boto3.client('ses', region_name='eu-central-1')  # Replace with your AWS region

    # Sender and recipient
    sender_email = 'rego@regomeszaros.awsapps.com'  # Your verified email
    recipient_email = event['recipient_email']  # Recipient's email from the event data

    # Email subject and body
    subject = 'Welcome to Our Service!'
    body_text = 'Hello,\n\nWelcome to our service. We are glad to have you!'
    body_html = """
    <html>
    <head></head>
    <body>
      <h1>Hello!</h1>
      <p>Welcome to our service. We are glad to have you!</p>
    </body>
    </html>
    """

    try:
        response = ses_client.send_email(
            Source=sender_email,
            Destination={
                'ToAddresses': [
                    recipient_email,
                ],
            },
            Message={
                'Subject': {
                    'Data': subject,
                    'Charset': 'UTF-8'
                },
                'Body': {
                    'Text': {
                        'Data': body_text,
                        'Charset': 'UTF-8'
                    },
                    'Html': {
                        'Data': body_html,
                        'Charset': 'UTF-8'
                    }
                }
            }
        )
        print(f"Email sent! Message ID: {response['MessageId']}")
    except Exception as e:
        print(f"Error sending email: {e}")
        raise e
