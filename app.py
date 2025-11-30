from flask import Flask

app = Flask(__name__)

@app.route("/")
def home():
    return "출퇴근 서버가 정상적으로 실행되었습니다. 🚀"

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
