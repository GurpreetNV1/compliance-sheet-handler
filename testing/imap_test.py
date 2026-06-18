from imap_handler.imap_client import ImapClient

client = ImapClient()

client.connect()

emails = client.fetch_new_emails()

for e in emails:
    print(e)

client.close()