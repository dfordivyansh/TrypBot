import google.generativeai as genai

# Configure API
genai.configure(
    api_key="AIzaSyBxE2nfUzKZOpmj45LFd30xbxfomKNwM8M"
)

# Load Gemini model
model = genai.GenerativeModel(
    "models/gemini-2.5-flash"
)

# Generate response
response = model.generate_content(
    "Best tourist places in Goa"
)

# Print response
print(response.text)