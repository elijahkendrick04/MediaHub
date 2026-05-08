"""Run the dev server: python -m mediahub.web"""
from .web import app

def main():
    app.run(host="0.0.0.0", port=int(__import__("os").environ.get("PORT", "5000")))

if __name__ == "__main__":
    main()
