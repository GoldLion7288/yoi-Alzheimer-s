from flask import Flask, render_template
from flask_socketio import SocketIO, emit
from flask_cors import CORS
from datetime import datetime

app = Flask(__name__)
app.config['SECRET_KEY'] = 'your-secret-key-change-this'

# Enable CORS for your frontend domain
CORS(app, origins=["*"])  # In production, replace * with your actual frontend URL

socketio = SocketIO(app, cors_allowed_origins="*")

# Store connected users and messages (in-memory, use database for production)
online_users = {}  # {sid: {'username': name, 'avatar': url}}
chat_messages = []

@app.route('/')
def index():
    return render_template('index.html')

@socketio.on('connect')
def handle_connect():
    print(f'Client connected: {request.sid}')

@socketio.on('disconnect')
def handle_disconnect():
    if request.sid in online_users:
        username = online_users[request.sid]['username']
        del online_users[request.sid]
        usernames = [u['username'] for u in online_users.values()]
        emit('user_left', {'username': username, 'users': usernames}, broadcast=True)
    print(f'Client disconnected: {request.sid}')

@socketio.on('join')
def handle_join(data):
    username = data.get('username', 'Anonymous')
    avatar = data.get('avatar', '')

    # Check if username is already taken
    existing_usernames = [u['username'].lower() for u in online_users.values()]
    if username.lower() in existing_usernames:
        emit('username_taken', {'message': 'Username is already taken'})
        return

    # Check if avatar is already taken
    existing_avatars = [u['avatar'] for u in online_users.values() if u['avatar']]
    if avatar and avatar in existing_avatars:
        emit('avatar_taken', {'message': 'Avatar is already taken', 'taken_avatars': existing_avatars})
        return

    online_users[request.sid] = {'username': username, 'avatar': avatar}

    # Send recent messages to the new user
    emit('message_history', chat_messages[-50:])  # Last 50 messages

    # Notify all users
    usernames = [u['username'] for u in online_users.values()]
    taken_avatars = [u['avatar'] for u in online_users.values() if u['avatar']]
    emit('user_joined', {
        'username': username,
        'users': usernames,
        'taken_avatars': taken_avatars
    }, broadcast=True)

@socketio.on('get_taken_avatars')
def handle_get_taken_avatars():
    taken_avatars = [u['avatar'] for u in online_users.values() if u['avatar']]
    emit('taken_avatars_list', {'taken_avatars': taken_avatars})

@socketio.on('message')
def handle_message(data):
    user_data = online_users.get(request.sid, {'username': 'Anonymous', 'avatar': ''})
    message = {
        'username': user_data['username'],
        'avatar': user_data['avatar'],
        'text': data.get('text', ''),
        'timestamp': datetime.now().strftime('%H:%M')
    }

    # Store message
    chat_messages.append(message)
    if len(chat_messages) > 100:  # Keep only last 100 messages
        chat_messages.pop(0)

    # Broadcast to all clients
    emit('new_message', message, broadcast=True)

@socketio.on('typing')
def handle_typing(data):
    user_data = online_users.get(request.sid, {'username': 'Anonymous', 'avatar': ''})
    emit('user_typing', {'username': user_data['username']}, broadcast=True, include_self=False)

# Import request for session ID access
from flask import request

if __name__ == '__main__':
    print("Starting chat server...")
    print("Server running at http://localhost:5000")
    print("\nTo expose to internet, use: ngrok http 5000")
    socketio.run(app, host='0.0.0.0', port=5000, debug=True)
