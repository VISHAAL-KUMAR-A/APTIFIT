import os
import pyttsx3
import speech_recognition as sr
from openai import OpenAI
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

# Get API key with clear error handling
api_key = os.getenv("OPENAI_API_KEY")
if not api_key:
    print("ERROR: OPENAI_API_KEY not found in environment variables")
    print("Please ensure you have a .env file with your API key or set it directly in the terminal")
    exit(1)

# Hard-code the API key directly in the script (only for testing, remove for production)
# api_key = "your-api-key-here"  # Uncomment this line and add your key for testing

# Initialize OpenAI client with better error handling
try:
    client = OpenAI(api_key=api_key)
    print("Successfully initialized OpenAI client")
except Exception as e:
    print(f"Failed to initialize OpenAI client: {str(e)}")
    exit(1)

# Initialize Text-to-Speech engine
try:
    engine = pyttsx3.init()
    voices = engine.getProperty('voices')
    engine.setProperty('voice', voices[1].id)  # Female voice
    engine.setProperty('rate', 180)  # Slightly faster speech rate
    print("Successfully initialized Text-to-Speech engine")
except Exception as e:
    print(f"Failed to initialize Text-to-Speech engine: {str(e)}")
    exit(1)

# Initialize speech recognizer
recognizer = sr.Recognizer()
recognizer.energy_threshold = 4000  # Adjust based on your environment
recognizer.dynamic_energy_threshold = True
recognizer.pause_threshold = 0.8  # Time of silence to consider end of phrase


def speak(text):
    """
    Function to convert text to speech
    """
    print(f"Assistant: {text}")
    try:
        engine.say(text)
        engine.runAndWait()
    except KeyboardInterrupt:
        # Handle Ctrl+C more gracefully
        print("\nInterrupted by user")
        exit(0)
    except Exception as e:
        print(f"Error in text-to-speech: {str(e)}")


def cmd():
    """
    Function to capture voice input from user
    """
    try:
        with sr.Microphone() as source:
            print("\nPlease wait for the system to boot up...")
            recognizer.adjust_for_ambient_noise(source, duration=1)
            print("Ready to use! Listening...")

            try:
                audio = recognizer.listen(
                    source, timeout=10, phrase_time_limit=5)
                print("Processing speech...")

                try:
                    command = recognizer.recognize_google(
                        audio, language='en-in')
                    command = command.lower()
                    print(f"User: {command}")
                    return command
                except sr.UnknownValueError:
                    print("Sorry, I couldn't understand that.")
                    return "none"
                except sr.RequestError as e:
                    print(
                        f"Could not request results from Google Speech Recognition service; {e}")
                    return "error"
            except sr.WaitTimeoutError:
                print("Listening timed out. Please try again.")
                return "timeout"
    except KeyboardInterrupt:
        print("\nInterrupted by user")
        exit(0)
    except Exception as e:
        print(f"Error in speech recognition: {str(e)}")
        return "error"


def get_gpt_response(prompt):
    """
    Function to get response from GPT model
    """
    if not prompt or prompt == "none" or prompt == "error" or prompt == "timeout":
        return "I didn't catch what you said. Could you please repeat?"

    try:
        # Test with a simple request first to check API connectivity
        print("Sending request to OpenAI...")
        response = client.chat.completions.create(
            model="gpt-3.5-turbo",
            messages=[
                {"role": "system", "content": "You are a helpful voice assistant. Keep responses concise and conversational."},
                {"role": "user", "content": prompt}
            ],
            max_tokens=150,
            temperature=0.7
        )
        return response.choices[0].message.content.strip()
    except KeyboardInterrupt:
        print("\nInterrupted by user")
        exit(0)
    except Exception as e:
        error_msg = str(e)
        print(f"OpenAI API Error: {error_msg}")

        if "401" in error_msg:
            return "I'm having trouble connecting. It seems there's an issue with the API key. Please check your configuration."
        elif "429" in error_msg:
            return "I'm receiving too many requests right now. Please try again in a moment."
        else:
            return "I'm sorry, I encountered an error while processing your request. Please try again."


def run_assistant():
    """
    Main function to run the voice assistant
    """
    try:
        speak("Hello, I am your voice assistant. How can I help you today?")

        while True:
            query = cmd()

            # Exit commands
            if query and any(word in query for word in ["goodbye", "bye", "exit", "stop", "quit"]):
                speak("Goodbye! Have a great day.")
                break

            # Skip if command not recognized
            if not query or query in ["none", "error", "timeout"]:
                speak("I didn't catch that. Could you please repeat?")
                continue

            # Get response from GPT
            response = get_gpt_response(query)
            speak(response)
    except KeyboardInterrupt:
        print("\nAssistant stopped by user")
    except Exception as e:
        print(f"Unexpected error: {str(e)}")
    finally:
        print("Voice assistant has been shut down")


if __name__ == "__main__":
    print("Starting voice assistant...")
    run_assistant()
