from app import create_app

app = create_app()

if __name__ == "__main__":
    app.run(debug=True)
    print("Available endpoints:")
    print(app.url_map)

