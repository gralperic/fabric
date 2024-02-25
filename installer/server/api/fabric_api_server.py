import jwt
import json
import openai
from flask import Flask, request, jsonify
from functools import wraps
import re
import requests
import os
from dotenv import load_dotenv
from importlib import resources


app = Flask(__name__)

@app.errorhandler(404)
def not_found(e):
    return jsonify({"error": "The requested resource was not found."}), 404

@app.errorhandler(500)
def server_error(e):
    return jsonify({"error": "An internal server error occurred."}), 500


# Load your OpenAI API key from a file
with open("/root/fabric_api/openai.key", "r") as key_file:
    api_key = key_file.read().strip()

## Define our own client
client_openai = openai.OpenAI(api_key = api_key)

# Read API tokens from the apikeys.json file
with open("/root/fabric_api/fabric_api_keys.json", "r") as tokens_file:
    valid_tokens = json.load(tokens_file)

# The function to check if the token is valid
def auth_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        # Get the authentication token from request header
        auth_token = request.headers.get("Authorization", "")

        # Remove any bearer token prefix if present
        if auth_token.lower().startswith("bearer "):
            auth_token = auth_token[7:]

        # Get API endpoint from request
        endpoint = request.path

        # Check if token is valid
        user = check_auth_token(auth_token, endpoint)
        if user == "Unauthorized: You are not authorized for this API":
            return jsonify({"error": user}), 401

        return f(*args, **kwargs)

    return decorated_function

# Check for a valid token/user for the given route
def check_auth_token(token, route):
    # Check if token is valid for the given route and return corresponding user
    if route in valid_tokens and token in valid_tokens[route]:
        return valid_tokens[route][token]
    else:
        return "Unauthorized: You are not authorized for this API"


# Define the allowlist of characters
ALLOWLIST_PATTERN = re.compile(r"^[a-zA-Z0-9\s.,;:!?\-]+$")


# Sanitize the content, sort of. Prompt injection is the main threat so this isn't a huge deal
def sanitize_content(content):
    """    Sanitize the content by removing characters that do not match the ALLOWLIST_PATTERN.

    Args:
        content (str): The content to be sanitized.

    Returns:
        str: The sanitized content.
    """

    return "".join(char for char in content if ALLOWLIST_PATTERN.match(char))


# Pull the URL content's from the GitHub repo
def fetch_content_from_url(url):
    """    Fetches content from the given URL.

    Args:
        url (str): The URL from which to fetch content.

    Returns:
        str: The sanitized content fetched from the URL.

    Raises:
        requests.RequestException: If an error occurs while making the request to the URL.
    """

    try:
        response = requests.get(url)
        response.raise_for_status()
        sanitized_content = sanitize_content(response.text)
        return sanitized_content
    except requests.RequestException as e:
        return str(e)


## APIs
# Make path mapping flexible and scalable
pattern_path_mappings = {
    "extwis": {"system_url": "https://raw.githubusercontent.com/gralperic/fabric/main/patterns/extract_wisdom/system.md",
               "user_url": "https://raw.githubusercontent.com/gralperic/fabric/main/patterns/extract_wisdom/user.md"},
    "summarize": {"system_url": "https://raw.githubusercontent.com/gralperic/fabric/main/patterns/summarize/system.md",
                  "user_url": "https://raw.githubusercontent.com/gralperic/fabric/main/patterns/summarize/user.md"}
} # Add more pattern with your desire path as a key in this dictionary

# /<pattern>
@app.route("/<pattern>", methods=["POST"])
@auth_required  # Require authentication
def milling(pattern):
    """    Combine fabric pattern with input from user and send to OpenAI's GPT-4 model.

    Returns:
        JSON: A JSON response containing the generated response or an error message.

    Raises:
        Exception: If there is an error during the API call.
    """

    data = request.get_json()

    # Warn if there's no input
    if "input" not in data:
        return jsonify({"error": "Missing input parameter"}), 400

    # Get data from client
    input_data = data["input"]

    # Set the system and user URLs
    urls = pattern_path_mappings[pattern]
    system_url, user_url = urls["system_url"], urls["user_url"]

    # Fetch the prompt content
    system_content = fetch_content_from_url(system_url)
    user_file_content = fetch_content_from_url(user_url)

    # Build the API call
    system_message = {"role": "system", "content": system_content}
    user_message = {"role": "user", "content": user_file_content + "\n" + input_data}
    messages = [system_message, user_message]
    try:
        response = client_openai.chat.completions.create(
            model="gpt-4-1106-preview",
            messages=messages,
            temperature=0.0,
            top_p=1,
            frequency_penalty=0.1,
            presence_penalty=0.1,
        )
        assistant_message = response.choices[0].message.content
        return jsonify({"response": assistant_message})
    except Exception as e:
        app.logger.error(f"Error occurred: {str(e)}")
        return jsonify({"error": "An error occurred while processing the request."}), 500



def main():
    """Runs the main fabric API backend server"""
    app.run(host="127.0.0.1", port=13337, debug=True)


if __name__ == "__main__":
    main()
