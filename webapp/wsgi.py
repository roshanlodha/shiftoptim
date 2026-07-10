"""Dev entrypoint: python -m webapp.wsgi"""

from .app import create_app

app = create_app()

if __name__ == "__main__":
    app.run(debug=True)
