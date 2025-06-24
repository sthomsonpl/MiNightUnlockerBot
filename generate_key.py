from cryptography.fernet import Fernet

def generate_key():
    key = Fernet.generate_key()
    print("🔐 Wygenerowany klucz szyfrowania (skopiuj i zachowaj bezpiecznie):\n")
    print(key.decode())


if __name__ == "__main__":
    generate_key()
