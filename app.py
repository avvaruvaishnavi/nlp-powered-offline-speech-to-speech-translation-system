from flask import Flask, render_template, request, jsonify
import vosk, sounddevice as sd, queue, json
import argostranslate.translate
import os
import tempfile
import sys
import logging

# Configure logging
logging.basicConfig(level=logging.INFO, 
                    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Import pyttsx3 for TTS (backup only)
import pyttsx3

# Pygame for audio playback
import pygame

# Suppress FutureWarnings
import warnings
warnings.filterwarnings("ignore", category=FutureWarning)

# Disable Flask's built-in dotenv loading
os.environ["FLASK_SKIP_DOTENV"] = "1"

app = Flask(__name__)

q = queue.Queue()
vosk.SetLogLevel(-1)

# Language configs
LANGUAGES = {
    "English": "en",
    "Hindi": "hi",
    "Spanish": "es",
    "German": "de",
    "Japanese": "ja",
    "Chinese": "zh",
}

MODEL_PATHS = {
    "en": "models/vosk-model-small-en-us-0.15",
    "hi": "models/vosk-model-small-hi-0.22",
    "es": "models/vosk-model-small-es-0.42",
    "de": "models/vosk-model-de-0.21",
    "ja": "models/vosk-model-small-ja-0.22",
    "zh": "models/vosk-model-small-cn-0.22",
}

# Set eSpeak path directly - hardcoded with the known correct path
ESPEAK_PATH = r"C:\Program Files (x86)\eSpeak\command_line\espeak.exe"
logger.info(f"Using eSpeak path: {ESPEAK_PATH}")

# Initialize translation modules
def initialize_translations():
    """Ensures all required language pairs are installed and ready for offline use"""
    try:
        # Check if argostranslate packages are installed
        installed_languages = argostranslate.translate.get_installed_languages()
        lang_codes = [lang.code for lang in installed_languages]
        logger.info(f"Installed languages: {lang_codes}")
        
        # Create a dictionary for easy access
        lang_dict = {lang.code: lang for lang in installed_languages}
        
        # Check all language pairs
        available_pairs = []
        missing_pairs = []
        
        # Test each language pair
        for source_code in LANGUAGES.values():
            for target_code in LANGUAGES.values():
                if source_code != target_code:
                    pair_name = f"{source_code}-{target_code}"
                    
                    # Skip if either language is missing
                    if source_code not in lang_codes or target_code not in lang_codes:
                        missing_langs = []
                        if source_code not in lang_codes:
                            missing_langs.append(source_code)
                        if target_code not in lang_codes:
                            missing_langs.append(target_code)
                        missing_pairs.append(f"{pair_name} (missing: {', '.join(missing_langs)})")
                        continue
                    
                    # Test translation
                    try:
                        translation = lang_dict[source_code].get_translation(lang_dict[target_code])
                        test_text = "hello" if source_code == "en" else "test"
                        test_result = translation.translate(test_text)
                        available_pairs.append(pair_name)
                        logger.info(f"Translation pair available: {pair_name}")
                    except Exception as e:
                        missing_pairs.append(f"{pair_name} (error: {str(e)})")
                        logger.warning(f"Translation pair failed: {pair_name} - {str(e)}")
        
        # Log summary
        logger.info(f"Available translation pairs: {len(available_pairs)}/{len(available_pairs) + len(missing_pairs)}")
        logger.info(f"Available pairs: {', '.join(available_pairs)}")
        if missing_pairs:
            logger.warning(f"Missing pairs: {', '.join(missing_pairs)}")
            logger.info("Consider installing missing language models using: python -m argostranslate.package download-packages")
            
        return lang_dict
    except Exception as e:
        logger.error(f"Error initializing translations: {str(e)}")
        
        # Return empty dict to avoid breaking the app completely
        return {}

lang_dict = initialize_translations()

def audio_callback(indata, frames, time, status):
    """Callback function for audio stream processing"""
    if status:
        logger.warning(f"Audio callback status: {status}")
    q.put(bytes(indata))

def recognize_speech(recognizer):
    """Records and recognizes speech using the Vosk model"""
    with sd.RawInputStream(
        samplerate=16000,
        blocksize=8000,
        dtype="int16",
        channels=1,
        callback=audio_callback,
    ):
        logger.info("Listening...")
        while True:
            data = q.get()
            if recognizer.AcceptWaveform(data):
                result = json.loads(recognizer.Result())
                recognized_text = result.get("text", "")
                logger.info(f"Recognized: '{recognized_text}'")
                return recognized_text

def translate_text(text, source, target):
    """Translates text between languages using ArgosTranslate"""
    if not text:
        return "No text recognized"

    if source == target:
        return text

    try:
        # Check if required languages are available
        if source not in lang_dict:
            logger.error(f"Source language {source} not installed")
            return f"[Translation failed: {source} language not installed]"
        if target not in lang_dict:
            logger.error(f"Target language {target} not installed")
            return f"[Translation failed: {target} language not installed]"

        # Try direct translation first
        try:
            translation = lang_dict[source].get_translation(lang_dict[target])
            result = translation.translate(text)
            logger.info(f"Translated '{text}' from {source} to {target}: '{result}'")
            return result
        except Exception as direct_error:
            logger.warning(f"Direct translation failed: {str(direct_error)}")
            
            # Try two-step translation via English if direct fails
            if source != "en" and target != "en":
                try:
                    logger.info(f"Attempting two-step translation via English")
                    # First translate to English
                    en_translation = lang_dict[source].get_translation(lang_dict["en"])
                    english_text = en_translation.translate(text)
                    logger.info(f"First step: {source} -> en: '{english_text}'")
                    
                    # Then translate from English to target
                    target_translation = lang_dict["en"].get_translation(lang_dict[target])
                    result = target_translation.translate(english_text)
                    logger.info(f"Second step: en -> {target}: '{result}'")
                    return result
                except Exception as two_step_error:
                    logger.error(f"Two-step translation also failed: {str(two_step_error)}")
            
            # If all translation attempts fail
            raise direct_error
            
    except Exception as e:
        logger.error(f"Translation error: {str(e)}")
        return f"[Translation Failed: {str(e)}]"

def speak_text(text, lang):
    """
    Speaks translated text using Microsoft Speech API for better language support,
    especially for Hindi
    """
    if not text:
        logger.warning("No text to speak")
        return
        
    logger.info(f"Speaking in {lang}: '{text}'")
    
    # Create temporary wav file
    temp_file = tempfile.NamedTemporaryFile(delete=False, suffix='.wav')
    temp_filename = temp_file.name
    temp_file.close()
    
    # Try methods in order of preference
    tts_success = False
    
    # 1. Try Microsoft Speech API for all languages, especially Hindi
    if not tts_success:
        try:
            logger.info(f"Trying Microsoft Speech API for {lang}")
            
            # Use Microsoft Speech API
            result = ms_speak(text, lang, temp_filename)
            
            if result:
                tts_success = True
                logger.info("Microsoft Speech API TTS succeeded")
        except Exception as e:
            logger.error(f"Microsoft Speech API error: {str(e)}")
    
    # 2. Fallback to eSpeak if Microsoft Speech API failed
    if not tts_success:
        try:
            logger.info(f"Trying eSpeak for {lang}")
            import subprocess
            
            # Save text to a file first to avoid encoding issues
            text_file = tempfile.NamedTemporaryFile(delete=False, mode='w', encoding='utf-8')
            text_file.write(text)
            text_file.close()
            text_path = text_file.name
            
            # Map to specific eSpeak voices
            espeak_voice_map = {
                "en": "en",
                "hi": "hi", 
                "es": "es",
                "de": "de",
                "ja": "en+f5",
                "zh": "en+f5"
            }
            
            voice = espeak_voice_map.get(lang, "en")
            
            # Extra parameters to improve speech quality
            extra_params = ["-s", "130", "-p", "50"]
            
            # Build command using file input to avoid encoding issues
            cmd = [ESPEAK_PATH, "-v", voice, "-w", temp_filename] + extra_params + ["-f", text_path]
            
            logger.info(f"Running eSpeak command: {' '.join(cmd)}")
            process = subprocess.run(cmd, capture_output=True, text=True)
            
            # Clean up text file
            os.unlink(text_path)
            
            if process.returncode != 0:
                logger.error(f"eSpeak error: {process.stderr}")
                raise Exception(f"eSpeak failed: {process.stderr}")
            
            # Check if file was created with content
            if os.path.exists(temp_filename) and os.path.getsize(temp_filename) > 1000:
                tts_success = True
                logger.info("eSpeak TTS saved to file successfully")
                
        except Exception as e:
            logger.error(f"eSpeak error: {str(e)}")
    
    # 3. Fallback to pyttsx3 if others failed
    if not tts_success:
        try:
            logger.info(f"Trying pyttsx3 for language: {lang}")
            engine = pyttsx3.init()
            
            # Adjust properties for better understandability
            engine.setProperty('rate', 120)  # Slower speech rate
            engine.setProperty('volume', 1.0)  # Maximum volume
            
            # Try to set voice that matches language
            for voice in engine.getProperty('voices'):
                voice_id = voice.id.lower()
                if lang in voice_id:
                    logger.info(f"Found matching voice: {voice.id}")
                    engine.setProperty('voice', voice.id)
                    break
            
            # Save to file instead of direct playback
            engine.save_to_file(text, temp_filename)
            engine.runAndWait()
            
            # Check if file was created with content
            if os.path.exists(temp_filename) and os.path.getsize(temp_filename) > 1000:
                tts_success = True
                logger.info("pyttsx3 TTS saved to file successfully")
        except Exception as e:
            logger.error(f"pyttsx3 error: {str(e)}")
    
    # If any TTS method succeeded, play the audio
    if tts_success:
        try:
            # Play audio with pygame
            pygame.mixer.init()
            pygame.mixer.music.load(temp_filename)
            pygame.mixer.music.play()
            
            # Wait for playback to finish
            while pygame.mixer.music.get_busy():
                import time
                time.sleep(0.1)
            
            # Clean up
            pygame.mixer.quit()
            logger.info("Audio playback completed")
        except Exception as e:
            logger.error(f"Audio playback error: {str(e)}")
            tts_success = False
    
    # Clean up temporary file
    try:
        if os.path.exists(temp_filename):
            os.unlink(temp_filename)
    except Exception as e:
        logger.error(f"Cleanup error: {str(e)}")
    
    # If all TTS methods failed, print the text as a last resort
    if not tts_success:
        print(f"\n===> [SPEECH ({lang})]: {text}\n")
        logger.error("All TTS methods failed - text output only")
    
    return tts_success

def ms_speak(text, lang, output_file):
    """
    Uses Microsoft Speech API (SAPI) to generate speech for multiple languages
    Especially good for Hindi and other languages
    """
    try:
        import win32com.client
        
        # Create SAPI voice object
        speaker = win32com.client.Dispatch("SAPI.SpVoice")
        
        # Language code mapping to Microsoft Speech language names
        # These are approximate and may vary by system
        ms_lang_map = {
            "en": "English",
            "hi": "Hindi",
            "es": "Spanish",
            "de": "German",
            "ja": "Japanese",
            "zh": "Chinese"
        }
        
        # The language name to search for
        search_lang = ms_lang_map.get(lang, "")
        
        # Find appropriate voice if available
        voice_found = False
        voices = speaker.GetVoices()
        
        for i in range(voices.Count):
            voice = voices.Item(i)
            voice_desc = voice.GetDescription().lower()
            
            # Check for language match
            if search_lang.lower() in voice_desc:
                speaker.Voice = voice
                voice_found = True
                logger.info(f"Found SAPI voice for {lang}: {voice.GetDescription()}")
                break
        
        if not voice_found:
            logger.info(f"No specific SAPI voice found for {lang}, using default voice")
        
        # Create file stream for output
        stream = win32com.client.Dispatch("SAPI.SpFileStream")
        stream.Open(output_file, 3)  # 3 = SSFMCreateForWrite
        
        # Set output to file
        old_output = speaker.AudioOutputStream
        speaker.AudioOutputStream = stream
        
        # Speak text
        speaker.Speak(text)
        
        # Close stream
        stream.Close()
        speaker.AudioOutputStream = old_output
        
        # Verify file was created
        result = os.path.exists(output_file) and os.path.getsize(output_file) > 1000
        logger.info(f"Microsoft Speech API result: {result}")
        return result
        
    except Exception as e:
        logger.error(f"Microsoft Speech API error: {str(e)}")
        return False

@app.route("/")
def index():
    return render_template("index.html", languages=LANGUAGES)

@app.route("/translate", methods=["POST"])
def translate():
    try:
        data = request.json
        source = data["source"]
        target = data["target"]
        source_code = LANGUAGES[source]
        target_code = LANGUAGES[target]

        logger.info(f"Translating from {source} ({source_code}) to {target} ({target_code})")

        # Check if model exists
        model_path = MODEL_PATHS[source_code]
        if not os.path.exists(model_path):
            error_msg = f"Model for {source} not found at {model_path}!"
            logger.error(error_msg)
            return jsonify({"error": error_msg})

        # Load speech recognition model
        try:
            model = vosk.Model(model_path)
            logger.info(f"Successfully loaded model from {model_path}")
        except Exception as e:
            error_msg = f"Failed to create model: {str(e)}"
            logger.error(error_msg)
            return jsonify({"error": error_msg})

        # Recognize speech
        recognizer = vosk.KaldiRecognizer(model, 16000)
        recognized = recognize_speech(recognizer)
        logger.info(f"Recognized text: '{recognized}'")

        # Check if translation is available
        can_translate = False
        
        # Validate language models are available
        if source_code in lang_dict and target_code in lang_dict:
            try:
                # Translate text
                translated = translate_text(recognized, source_code, target_code)
                logger.info(f"Translated text: '{translated}'")
                
                # Speak translated text
                speak_text(translated, target_code)
                
                return jsonify({
                    "recognized": recognized, 
                    "translated": translated
                })
                
            except Exception as translation_error:
                error_msg = f"Translation failed: {str(translation_error)}"
                logger.error(error_msg)
                return jsonify({
                    "error": error_msg,
                    "recognized": recognized,
                    "can_translate": False
                })
        else:
            missing_models = []
            if source_code not in lang_dict:
                missing_models.append(f"{source} ({source_code})")
            if target_code not in lang_dict:
                missing_models.append(f"{target} ({target_code})")
                
            error_msg = f"Missing translation models for: {', '.join(missing_models)}"
            logger.error(error_msg)
            return jsonify({
                "error": error_msg,
                "recognized": recognized,
                "can_translate": False,
                "missing_models": missing_models
            })

    except Exception as e:
        error_msg = f"Error in translation route: {str(e)}"
        logger.error(error_msg)
        return jsonify({"error": error_msg})

@app.route("/check_models", methods=["GET"])
def check_models():
    """API route to check available models and translations"""
    available_models = {}
    
    # Check speech recognition models
    for lang_code, path in MODEL_PATHS.items():
        available_models[lang_code] = {
            "speech_recognition": os.path.exists(path),
            "path": path
        }
    
    # Check translation capabilities
    translation_capabilities = {}
    for source in LANGUAGES.values():
        for target in LANGUAGES.values():
            if source != target:
                source_available = source in lang_dict
                target_available = target in lang_dict
                can_translate = False
                
                if source_available and target_available:
                    try:
                        translation = lang_dict[source].get_translation(lang_dict[target])
                        can_translate = True
                    except:
                        can_translate = False
                        
                key = f"{source}-{target}"
                translation_capabilities[key] = {
                    "source_available": source_available,
                    "target_available": target_available,
                    "can_translate": can_translate
                }
    
    # Check TTS capabilities
    tts_capabilities = {}
    
    # Check eSpeak availability with hardcoded path
    espeak_available = os.path.exists(ESPEAK_PATH)
    
    # Also check pyttsx3 voices as backup
    try:
        engine = pyttsx3.init()
        voices = engine.getProperty('voices')
        
        for lang_code in LANGUAGES.values():
            # Check for direct match in voice ID
            voice_found = any(lang_code in voice.id.lower() for voice in voices)
            
            tts_capabilities[lang_code] = {
                "espeak": espeak_available,
                "pyttsx3": voice_found,
            }
    except Exception as e:
        logger.error(f"Error checking TTS capabilities: {str(e)}")
        # Fallback
        for lang_code in LANGUAGES.values():
            tts_capabilities[lang_code] = {
                "espeak": espeak_available,
                "pyttsx3": False
            }
    
    return jsonify({
        "speech_recognition_models": available_models,
        "translation_capabilities": translation_capabilities,
        "tts_capabilities": tts_capabilities,
        "espeak_installed": espeak_available,
        "espeak_path": ESPEAK_PATH
    })

@app.route("/check_espeak", methods=["GET"])
def check_espeak():
    """Check if eSpeak is installed and working using hardcoded path"""
    try:
        import os.path
        
        if not os.path.exists(ESPEAK_PATH):
            return jsonify({
                "installed": False,
                "message": f"eSpeak not found at {ESPEAK_PATH}. Please check the path."
            })
        
        # Test eSpeak by generating a simple message
        import subprocess
        test_message = "eSpeak test successful"
        
        # Run eSpeak with version flag
        process = subprocess.run([ESPEAK_PATH, "--version"], capture_output=True, text=True)
        
        if process.returncode != 0:
            return jsonify({
                "installed": True,
                "working": False,
                "message": f"eSpeak found at {ESPEAK_PATH} but not working properly: {process.stderr}"
            })
        
        version_info = process.stdout.strip()
        
        # Try to run a simple test
        test_file = tempfile.NamedTemporaryFile(delete=False, suffix='.wav')
        test_filename = test_file.name
        test_file.close()
        
        test_process = subprocess.run(
            [ESPEAK_PATH, "-v", "en", "-w", test_filename, test_message], 
            capture_output=True, 
            text=True
        )
        
        if test_process.returncode != 0:
            return jsonify({
                "installed": True,
                "working": False,
                "version": version_info,
                "message": f"eSpeak found but couldn't generate audio: {test_process.stderr}"
            })
        
        # Clean up test file
        os.unlink(test_filename)
        
        # Check available voices
        voices_process = subprocess.run([ESPEAK_PATH, "--voices"], capture_output=True, text=True)
        voices_output = voices_process.stdout if voices_process.returncode == 0 else "Could not list voices"
        
        # Extract relevant language voices
        relevant_voices = {}
        for lang_name, lang_code in LANGUAGES.items():
            if voices_output != "Could not list voices":
                relevant_voices[lang_code] = [
                    line for line in voices_output.split('\n') 
                    if f" {lang_code} " in line or f" {lang_code}_" in line
                ]
        
        return jsonify({
            "installed": True,
            "working": True,
            "version": version_info,
            "path": ESPEAK_PATH,
            "relevant_voices": relevant_voices
        })
        
    except Exception as e:
        return jsonify({
            "installed": False,
            "error": str(e),
            "message": f"Error checking eSpeak installation: {str(e)}"
        })

if __name__ == "__main__":
    # Print system information for debugging
    logger.info(f"Python version: {sys.version}")
    logger.info(f"Current working directory: {os.getcwd()}")
    logger.info(f"Available speech models: {[path for path in MODEL_PATHS.values() if os.path.exists(path)]}")
    
    # Check if eSpeak is installed using hardcoded path
    if os.path.exists(ESPEAK_PATH):
        logger.info(f"eSpeak found at: {ESPEAK_PATH}")
        logger.info("eSpeak is installed - offline TTS should work for all languages")
    else:
        logger.warning(f"eSpeak NOT found at: {ESPEAK_PATH}")
        logger.warning("Offline TTS may not work properly!")
        logger.warning(f"Please make sure eSpeak is installed at {ESPEAK_PATH}")
    
    # Initialize pygame for audio playback
    pygame.init()
    
    # Run the Flask app
    app.run(debug=False, host='0.0.0.0', port=5000)