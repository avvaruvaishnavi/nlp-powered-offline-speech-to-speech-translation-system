import os
import sys
import argostranslate.translate
import argostranslate.package
import vosk

def check_vosk_models():
    print("=== VOSK MODEL CHECK ===")
    model_paths = {
        "en": "models/vosk-model-small-en-us-0.15",
        "hi": "models/vosk-model-small-hi-0.22",
        "es": "models/vosk-model-small-es-0.42",
        "de": "models/vosk-model-small-de-0.15",
        "ja": "models/vosk-model-small-ja-0.22",
        "zh": "models/vosk-model-small-cn-0.22"
    }
    
    print(f"Current working directory: {os.getcwd()}")
    
    for lang, path in model_paths.items():
        if os.path.exists(path):
            print(f"✓ {lang}: Model found at {path}")
            try:
                model = vosk.Model(path)
                print(f"  ✓ Model loaded successfully")
            except Exception as e:
                print(f"  ✗ Failed to load model: {str(e)}")
        else:
            print(f"✗ {lang}: Model NOT found at {path}")
    
    print("\nIf models are missing, download them from: https://alphacephei.com/vosk/models")

def check_translation_modules():
    print("\n=== ARGOSTRANSLATE CHECK ===")
    
    # Check installed packages
    print("Checking installed translation packages...")
    installed_languages = argostranslate.translate.get_installed_languages()
    
    if not installed_languages:
        print("No translation packages installed.")
        print("Installing English <-> Hindi packages...")
        
        try:
            # Update package index
            argostranslate.package.update_package_index()
            available_packages = argostranslate.package.get_available_packages()
            
            # Find and install English <-> Hindi packages
            for from_code, to_code in [('en', 'hi'), ('hi', 'en')]:
                package = next(
                    (pkg for pkg in available_packages if pkg.from_code == from_code and pkg.to_code == to_code), 
                    None
                )
                
                if package:
                    print(f"Installing {from_code} -> {to_code} package...")
                    argostranslate.package.install_from_path(package.download())
                else:
                    print(f"✗ No {from_code} -> {to_code} package available")
                    
            # Refresh installed languages
            installed_languages = argostranslate.translate.get_installed_languages()
        except Exception as e:
            print(f"Error installing packages: {str(e)}")
    
    # Display available translation pairs
    print("\nAvailable translation pairs:")
    
    if installed_languages:
        lang_dict = {lang.code: lang for lang in installed_languages}
        
        for from_lang in installed_languages:
            translations = from_lang.translations
            for translation in translations:
                print(f"✓ {from_lang.code} -> {translation.to_code}")
                
        # Check specifically for English <-> Hindi
        has_en_hi = any(lang.code == 'en' and any(t.to_code == 'hi' for t in lang.translations) for lang in installed_languages)
        has_hi_en = any(lang.code == 'hi' and any(t.to_code == 'en' for t in lang.translations) for lang in installed_languages)
        
        if has_en_hi:
            print("\n✓ English -> Hindi translation available")
        else:
            print("\n✗ English -> Hindi translation NOT available")
            
        if has_hi_en:
            print("✓ Hindi -> English translation available")
        else:
            print("✗ Hindi -> English translation NOT available")
    else:
        print("No translation packages available after installation attempt.")

if __name__ == "__main__":
    print(f"Python version: {sys.version}")
    check_vosk_models()
    check_translation_modules()
    print("\n=== TROUBLESHOOTING TIPS ===")
    print("1. Make sure all models are downloaded to the correct paths")
    print("2. Ensure you have proper read permissions for the model directories")
    print("3. For English-Hindi translation, both language pairs need to be installed")
    print("4. Run this script with administrator privileges if model loading fails")