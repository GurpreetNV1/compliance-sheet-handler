from attachment_reader.processor import AttachmentProcessor

processor = AttachmentProcessor()

data = processor.process_folder("storage/email_1/attachments")

print("\nFINAL RESULT:")
for d in data:
    print(d)