import os
import pyttsx3
import speech_recognition as sr
from openai import OpenAI

# Load API key from environment variable
api_key = os.getenv("OPENAI_API_KEY")
client = OpenAI(api_key=api_key)

# Initialize Text-to-Speech engine
engine = pyttsx3.init()
voices = engine.getProperty('voices')
engine.setProperty('voice', voices[1].id)
recognizer = sr.Recognizer()


def speak(text):
    """
    Function to convert text to speech
    """
    print(f"Assistant: {text}")
    engine.say(text)
    engine.runAndWait()


def cmd():
    """
    Function to capture voice input from user
    """
    with sr.Microphone() as source:
        print("Please wait for the system to boot up")
        recognizer.adjust_for_ambient_noise(source, duration=0.5)
        print("Ready to use")
        audio = recognizer.listen(source)
        try:
            command = recognizer.recognize_google(audio, language='en-in')
            command = command.lower()
            print(f"User: {command}")
            return command
        except Exception as e:
            print("Say that again")
            return "none"


def get_gpt_response(prompt):
    """
    Function to get response from GPT model
    """
    try:
        response = client.chat.completions.create(
            model="gpt-3.5-turbo",
            messages=[
                {"role": "system", "content": "You are a helpful voice assistant."},
                {"role": "user", "content": prompt}
            ],
            max_tokens=150
        )
        return response.choices[0].message.content.strip()
    except Exception as e:
        return f"Sorry, I encountered an error: {str(e)}"


def run_assistant():
    """
    Main function to run the voice assistant
    """
    speak("Hello, I am your voice assistant. How can I help you today?")

    while True:
        query = cmd()

        # Exit commands
        if "goodbye" in query or "bye" in query or "exit" in query or "stop" in query:
            speak("Goodbye! Have a great day.")
            break

        # Skip if command not recognized
        if query == "none":
            speak("I didn't catch that. Could you please repeat?")
            continue

        # Get response from GPT
        response = get_gpt_response(query)
        speak(response)


if __name__ == "__main__":
    run_assistant()
