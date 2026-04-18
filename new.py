from google import genai
from api import API_KEY

# Import API key from api.py and initialize the client.
client = genai.Client(api_key=API_KEY)

response = client.models.generate_content(
    model="gemini-3-flash-preview", contents="Explain how AI works in a few words"
)
print(response.text)