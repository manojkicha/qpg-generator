# Add this at the top of your script
import ssl
import certifi
import os

# Set certificate paths
os.environ['REQUESTS_CA_BUNDLE'] = certifi.where()
os.environ['SSL_CERT_FILE'] = certifi.where()

# Now run DocTR
from doctr.io import DocumentFile
from doctr.models import ocr_predictor

try:
    model = ocr_predictor(pretrained=True)
    print("Model loaded successfully!")
except Exception as e:
    print(f"Error: {e}")


from doctr.io import DocumentFile
from doctr.models import ocr_predictor

model = ocr_predictor(pretrained=True)
doc = DocumentFile.from_pdf("Featherbook.pdf")
#result = model(doc)
pages = [doc[4]]                                  # 0-indexed slice, pages 1-3
result = model(pages)

print(result)