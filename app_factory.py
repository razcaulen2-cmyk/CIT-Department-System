import os

from flask import Flask, render_template

from routes import admin_bp, api_bp, auth_bp, events_bp, payments_bp, student_bp


def create_app() -> Flask:
    app = Flask(__name__)

    app.register_blueprint(admin_bp)
    app.register_blueprint(student_bp)
    app.register_blueprint(auth_bp)
    app.register_blueprint(payments_bp)
    app.register_blueprint(events_bp)
    app.register_blueprint(api_bp)

    app.secret_key = os.getenv("FLASK_SECRET_KEY", "dev-only-change-me")
    app.config["SESSION_COOKIE_SECURE"] = False
    app.config["SESSION_COOKIE_HTTPONLY"] = True
    app.config["SESSION_COOKIE_SAMESITE"] = "Lax"

    @app.route("/")
    def home():
        return render_template("public/index.html")

    return app


app = create_app()
