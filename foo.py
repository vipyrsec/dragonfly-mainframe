import json
import urllib.error
import urllib.request

url = "http://0.0.0.0:8000/update-rules/"

# Data to be sent in the request body
data = {"key": "value"}

# Encode the data as JSON
data = json.dumps(data).encode("utf-8")

try:
    # Send the POST request
    req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"})
    response = urllib.request.urlopen(req)

    # Read and print the response
    response_data = response.read().decode("utf-8")
    print("Response body:", response_data)
    print("Response status code:", response.code)

except urllib.error.HTTPError as e:
    print("HTTP error:", e.code)
except urllib.error.URLError as e:
    print("URL error:", e.reason)
