from flask import Flask, render_template, request
from flask_socketio import SocketIO, emit
from flask_cors import CORS
from datetime import datetime
import uuid
import os
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

app = Flask(__name__)
app.config['SECRET_KEY'] = os.getenv('SECRET_KEY', 'your-secret-key-change-this')

# Get CORS origins from environment
cors_origins = os.getenv('CORS_ORIGINS', '*')
if cors_origins != '*':
    cors_origins = [origin.strip() for origin in cors_origins.split(',')]

# Enable CORS for your frontend domain
CORS(app, origins=cors_origins if cors_origins != '*' else ["*"])

socketio = SocketIO(app, cors_allowed_origins=cors_origins if cors_origins != '*' else "*")

# Store connected users and messages (in-memory, use database for production)
online_users = {}  # {sid: {'username': name, 'avatar': url}}
chat_messages = []
blocked_users = []  # List of blocked usernames

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/admin')
def admin():
    return render_template('admin.html')

@socketio.on('connect')
def handle_connect():
    print(f'Client connected: {request.sid}')

@socketio.on('disconnect')
def handle_disconnect():
    if request.sid in online_users:
        username = online_users[request.sid]['username']
        del online_users[request.sid]
        usernames = [u['username'] for u in online_users.values()]
        users_list = [{'username': u['username'], 'avatar': u['avatar']} for u in online_users.values()]
        emit('user_left', {'username': username, 'users': usernames}, broadcast=True)
        emit('online_users_list', {'users': users_list}, broadcast=True)
    print(f'Client disconnected: {request.sid}')

@socketio.on('join')
def handle_join(data):
    username = data.get('username', 'Anonymous')
    avatar = data.get('avatar', '')

    # Check if username is blocked
    if username.lower() in [u.lower() for u in blocked_users]:
        emit('user_blocked', {'message': 'You have been blocked from this chat'})
        return

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

    # Send online users list
    users_list = [{'username': u['username'], 'avatar': u['avatar']} for u in online_users.values()]
    emit('online_users_list', {'users': users_list})

    # Notify all users
    usernames = [u['username'] for u in online_users.values()]
    taken_avatars = [u['avatar'] for u in online_users.values() if u['avatar']]
    emit('user_joined', {
        'username': username,
        'users': usernames,
        'taken_avatars': taken_avatars
    }, broadcast=True)

    # Broadcast updated online users list to all
    emit('online_users_list', {'users': users_list}, broadcast=True)

@socketio.on('get_taken_avatars')
def handle_get_taken_avatars():
    taken_avatars = [u['avatar'] for u in online_users.values() if u['avatar']]
    emit('taken_avatars_list', {'taken_avatars': taken_avatars})

@socketio.on('message')
def handle_message(data):
    user_data = online_users.get(request.sid, {'username': 'Anonymous', 'avatar': ''})
    message = {
        'id': str(uuid.uuid4()),
        'username': user_data['username'],
        'avatar': user_data['avatar'],
        'text': data.get('text', ''),
        'timestamp': datetime.now().strftime('%H:%M'),
        'replyTo': data.get('replyTo', None)
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

@socketio.on('private_message')
def handle_private_message(data):
    """Handle private/direct messages between users"""
    sender_data = online_users.get(request.sid)
    if not sender_data:
        return

    target_username = data.get('to', '')
    message_text = data.get('text', '')

    if not target_username or not message_text:
        return

    # Find the target user's socket ID
    target_sid = None
    for sid, user_data in online_users.items():
        if user_data['username'].lower() == target_username.lower():
            target_sid = sid
            break

    if target_sid:
        # Send the private message to the target user
        emit('private_message', {
            'from': sender_data['username'],
            'fromAvatar': sender_data['avatar'],
            'text': message_text,
            'timestamp': datetime.now().strftime('%H:%M')
        }, room=target_sid)

# Admin functions
@socketio.on('admin_get_data')
def handle_admin_get_data():
    users_list = [{'username': u['username'], 'avatar': u['avatar']} for u in online_users.values()]
    emit('admin_data', {
        'online_users': users_list,
        'blocked_users': blocked_users,
        'message_count': len(chat_messages)
    })

@socketio.on('admin_block_user')
def handle_admin_block_user(data):
    username = data.get('username', '')
    if not username:
        emit('admin_action_result', {'success': False, 'message': 'Username required'})
        return

    # Add to blocked list if not already there
    if username.lower() not in [u.lower() for u in blocked_users]:
        blocked_users.append(username)

    # Find and kick the user if online
    sid_to_kick = None
    for sid, user_data in online_users.items():
        if user_data['username'].lower() == username.lower():
            sid_to_kick = sid
            break

    if sid_to_kick:
        # Notify the user they've been blocked
        emit('user_blocked', {'message': 'You have been blocked by an administrator'}, room=sid_to_kick)
        # Remove from online users
        del online_users[sid_to_kick]
        # Notify all users
        users_list = [{'username': u['username'], 'avatar': u['avatar']} for u in online_users.values()]
        emit('online_users_list', {'users': users_list}, broadcast=True)
        emit('user_left', {'username': username, 'users': [u['username'] for u in online_users.values()]}, broadcast=True)

    # Send updated data to admin
    emit('admin_action_result', {'success': True, 'message': f'{username} has been blocked'})
    emit('admin_blocked_update', {'blocked_users': blocked_users})
    users_list = [{'username': u['username'], 'avatar': u['avatar']} for u in online_users.values()]
    emit('admin_user_list_update', {'online_users': users_list})

@socketio.on('admin_unblock_user')
def handle_admin_unblock_user(data):
    username = data.get('username', '')
    if not username:
        emit('admin_action_result', {'success': False, 'message': 'Username required'})
        return

    # Remove from blocked list
    blocked_users[:] = [u for u in blocked_users if u.lower() != username.lower()]

    emit('admin_action_result', {'success': True, 'message': f'{username} has been unblocked'})
    emit('admin_blocked_update', {'blocked_users': blocked_users})

@socketio.on('admin_kick_user')
def handle_admin_kick_user(data):
    username = data.get('username', '')
    if not username:
        emit('admin_action_result', {'success': False, 'message': 'Username required'})
        return

    # Find and kick the user
    sid_to_kick = None
    for sid, user_data in online_users.items():
        if user_data['username'].lower() == username.lower():
            sid_to_kick = sid
            break

    if sid_to_kick:
        # Notify the user they've been kicked
        emit('user_kicked', {'message': 'You have been kicked by an administrator'}, room=sid_to_kick)
        # Remove from online users
        del online_users[sid_to_kick]
        # Notify all users
        users_list = [{'username': u['username'], 'avatar': u['avatar']} for u in online_users.values()]
        emit('online_users_list', {'users': users_list}, broadcast=True)
        emit('user_left', {'username': username, 'users': [u['username'] for u in online_users.values()]}, broadcast=True)

        emit('admin_action_result', {'success': True, 'message': f'{username} has been kicked'})
        emit('admin_user_list_update', {'online_users': users_list})
    else:
        emit('admin_action_result', {'success': False, 'message': f'{username} is not online'})

@socketio.on('admin_delete_user')
def handle_admin_delete_user(data):
    username = data.get('username', '')
    if not username:
        emit('admin_action_result', {'success': False, 'message': 'Username required'})
        return

    # Remove from blocked list
    blocked_users[:] = [u for u in blocked_users if u.lower() != username.lower()]

    emit('admin_action_result', {'success': True, 'message': f'{username} has been deleted from blocked list'})
    emit('admin_blocked_update', {'blocked_users': blocked_users})

if __name__ == '__main__':
    port = int(os.getenv('PORT', 5000))
    host = os.getenv('HOST', '0.0.0.0')
    debug = os.getenv('FLASK_DEBUG', 'False').lower() == 'true'

    print("Starting chat server...")
    print(f"Server running at http://{host}:{port}")
    print(f"Admin panel at http://{host}:{port}/admin")
    print("\nTo expose to internet, use: ngrok http 5000")
    socketio.run(app, host=host, port=port, debug=debug)
