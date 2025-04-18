from your_app import app, db  # adjust to your actual module names

with app.app_context():
    db.drop_all()
    db.session.commit()