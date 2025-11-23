from reportlab.pdfgen import canvas

def create_pdf(filename):
    c = canvas.Canvas(filename)
    c.drawString(100, 750, "CONFIDENTIAL DOCUMENT")
    c.drawString(100, 700, "The secret password is 'BLUEBERRY'.")
    c.drawString(100, 650, "Please do not share this with anyone.")
    c.save()

if __name__ == "__main__":
    create_pdf("secret.pdf")
    print("Created secret.pdf")
