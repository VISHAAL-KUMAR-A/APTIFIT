import uvicorn
import os
import django
import logging
import sys

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(sys.stdout)
    ]
)

# Set the Django settings module
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'aptifit.settings')

# Initialize Django
django.setup()

# Run uvicorn
if __name__ == "__main__":
    uvicorn.run(
        "aptifit.custom_asgi:application",
        host="127.0.0.1",
        port=8000,
        log_level="info",
        reload=True
    )
