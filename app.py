from flask import Flask, render_template_string, request, jsonify
from flask_socketio import SocketIO, emit, join_room, leave_room, rooms
import random
import os
import string

app = Flask(__name__)
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'ludo-secret-key-2025')

# IMPORTANT: Production configuration for Render/Heroku/Railway
socketio = SocketIO(
    app,
    cors_allowed_origins="*",
    async_mode='threading',
    logger=True,
    engineio_logger=True,
    ping_timeout=60,
    ping_interval=25
)

SAFE_POSITIONS = [0, 8, 13, 21, 26, 34, 39, 47]

# Global storage for game rooms
game_rooms = {}

def generate_room_code():
    """Generate a unique 6-character room code"""
    while True:
        code = ''.join(random.choices(string.ascii_uppercase + string.digits, k=6))
        if code not in game_rooms:
            return code

def create_game_state():
    """Create a fresh game state"""
    return {
        'mode': None,
        'num_players': 4,
        'active_colors': [],
        'user_color': None,
        'turn': None,
        'rolled_value': None,
        'can_move': False,
        'players': {
            'red':    {'tokens': [-1, -1, -1, -1], 'path_start': 0},
            'green':  {'tokens': [-1, -1, -1, -1], 'path_start': 13},
            'yellow': {'tokens': [-1, -1, -1, -1], 'path_start': 26},
            'blue':   {'tokens': [-1, -1, -1, -1], 'path_start': 39}
        },
        'log': "Waiting for game to start...",
        'game_started': False,
        'turn_order': [],
        'room_code': None,
        'player_sessions': {},
        'connected_players': 0
    }

@app.route('/')
def index():
    return render_template_string(HTML_CODE)

@app.route('/health')
def health():
    """Health check endpoint for monitoring"""
    return jsonify({'status': 'ok', 'rooms': len(game_rooms)})

@app.route('/api/create-room', methods=['POST'])
def create_room():
    """API endpoint to create a new game room"""
    data = request.json
    room_code = generate_room_code()
    
    game_state = create_game_state()
    game_state['room_code'] = room_code
    game_state['mode'] = data.get('mode', 'multiplayer')
    game_state['num_players'] = data.get('num_players', 4)
    
    game_rooms[room_code] = game_state
    
    return jsonify({
        'success': True,
        'room_code': room_code,
        'message': f'Room {room_code} created successfully!'
    })

@app.route('/api/join-room/<room_code>', methods=['GET'])
def check_room(room_code):
    """API endpoint to check if a room exists and get its status"""
    room_code = room_code.upper()
    
    if room_code in game_rooms:
        game = game_rooms[room_code]
        return jsonify({
            'success': True,
            'exists': True,
            'room_code': room_code,
            'players_connected': game['connected_players'],
            'max_players': game['num_players'],
            'game_started': game['game_started'],
            'available_colors': [c for c in ['red', 'green', 'yellow', 'blue'] 
                               if c not in game['player_sessions'].values()]
        })
    else:
        return jsonify({
            'success': False,
            'exists': False,
            'message': 'Room not found'
        })

@socketio.on('connect')
def handle_connect():
    print(f"✅ Client connected: {request.sid}")
    emit('connection_status', {'status': 'connected', 'session_id': request.sid})

@socketio.on('disconnect')
def handle_disconnect():
    print(f"❌ Client disconnected: {request.sid}")
    
    for room_code, game_state in list(game_rooms.items()):
        if request.sid in game_state['player_sessions']:
            game_state['connected_players'] -= 1
            color = game_state['player_sessions'][request.sid]
            del game_state['player_sessions'][request.sid]
            
            game_state['log'] = f"❌ {color.upper()} player disconnected"
            emit('update_state', game_state, room=room_code)

@socketio.on('join_room_with_code')
def handle_join_room(data):
    """Join a specific game room with a code"""
    room_code = data.get('room_code', '').upper()
    selected_color = data.get('color')
    
    if room_code not in game_rooms:
        emit('error', {'message': 'Room not found'})
        return
    
    game_state = game_rooms[room_code]
    
    if selected_color in game_state['player_sessions'].values():
        emit('error', {'message': 'Color already taken'})
        return
    
    join_room(room_code)
    game_state['player_sessions'][request.sid] = selected_color
    game_state['connected_players'] += 1
    
    print(f"🎮 Player {request.sid} joined room {room_code} as {selected_color}")
    
    game_state['log'] = f"✅ {selected_color.upper()} player joined! ({game_state['connected_players']}/{game_state['num_players']})"
    emit('room_joined', {'room_code': room_code, 'color': selected_color})
    emit('update_state', game_state, room=room_code)

@socketio.on('start_game')
def handle_start_game(data):
    room_code = data.get('room_code')
    
    if room_code and room_code in game_rooms:
        game_state = game_rooms[room_code]
        print(f"🎮 Using existing room {room_code}")
    else:
        room_code = f"LOCAL_{request.sid}"
        game_state = create_game_state()
        game_rooms[room_code] = game_state
        join_room(room_code)
        print(f"🎮 Created local room {room_code}")
    
    game_state['mode'] = data.get('mode', 'multiplayer')
    game_state['num_players'] = data.get('num_players', 4)
    game_state['user_color'] = data.get('user_color')
    game_state['game_started'] = True
    game_state['room_code'] = room_code
    
    if data['num_players'] == 2:
        if data['mode'] == 'computer':
            opp = {'red':'yellow', 'yellow':'red', 'green':'blue', 'blue':'green'}
            game_state['active_colors'] = [data['user_color'], opp[data['user_color']]]
        else:
            if room_code.startswith('LOCAL_'):
                game_state['active_colors'] = ['red', 'yellow']
            else:
                game_state['active_colors'] = list(game_state['player_sessions'].values())
    else:
        if room_code.startswith('LOCAL_'):
            game_state['active_colors'] = ['red', 'green', 'yellow', 'blue']
        else:
            game_state['active_colors'] = list(game_state['player_sessions'].values())
    
    for color in game_state['active_colors']:
        game_state['players'][color]['tokens'] = [-1, -1, -1, -1]
    
    game_state['turn_order'] = game_state['active_colors'][:]
    game_state['turn'] = game_state['turn_order'][0]
    game_state['rolled_value'] = None
    game_state['can_move'] = False
    game_state['log'] = f"🎮 {game_state['turn'].upper()}'s TURN - CLICK DICE TO ROLL!"
    
    print(f"✅ Game initialized in room {room_code}")
    
    emit('room_assigned', {'room_code': room_code})
    emit('update_state', game_state, room=room_code)
    
    if game_state['mode'] == 'computer' and game_state['turn'] != game_state['user_color']:
        socketio.start_background_task(bot_turn, room_code)

@socketio.on('roll_dice')
def handle_roll(data=None):
    room_code = data.get('room_code') if data else None
    
    if not room_code or room_code not in game_rooms:
        print(f"❌ Invalid room: {room_code}")
        return
    
    game_state = game_rooms[room_code]
    
    if not game_state['game_started'] or game_state['rolled_value'] is not None:
        return
    
    if not room_code.startswith('LOCAL_'):
        player_color = game_state['player_sessions'].get(request.sid)
        if player_color and player_color != game_state['turn']:
            return
    
    if game_state['mode'] == 'computer' and game_state['turn'] != game_state['user_color']:
        return
    
    roll_dice(room_code)

def roll_dice(room_code):
    game_state = game_rooms[room_code]
    
    val = random.randint(1, 6)
    game_state['rolled_value'] = val
    game_state['log'] = f"🎲 {game_state['turn'].upper()} ROLLED {val}!"
    
    tokens = game_state['players'][game_state['turn']]['tokens']
    has_moves = any((t == -1 and val == 6) or (t >= 0 and t + val <= 57) for t in tokens)
    
    if not has_moves:
        game_state['log'] += " ❌ NO VALID MOVES!"
        socketio.emit('update_state', game_state, room=room_code)
        socketio.sleep(2.0)
        next_turn(room_code)
    else:
        game_state['can_move'] = True
        game_state['log'] += " ✅ CLICK A TOKEN TO MOVE!"
        socketio.emit('update_state', game_state, room=room_code)
        
        if game_state['mode'] == 'computer' and game_state['turn'] != game_state['user_color']:
            socketio.start_background_task(bot_make_move, room_code)

@socketio.on('move_token')
def handle_move(data):
    room_code = data.get('room_code')
    
    if not room_code or room_code not in game_rooms:
        return
    
    game_state = game_rooms[room_code]
    
    if not game_state['can_move']:
        return
    
    if not room_code.startswith('LOCAL_'):
        player_color = game_state['player_sessions'].get(request.sid)
        if player_color and player_color != game_state['turn']:
            return
    
    if game_state['mode'] == 'computer' and game_state['turn'] != game_state['user_color']:
        return
    
    move_token(data['token_index'], room_code)

def move_token(token_idx, room_code):
    game_state = game_rooms[room_code]
    player = game_state['turn']
    tokens = game_state['players'][player]['tokens']
    roll = game_state['rolled_value']
    captured = False
    
    if tokens[token_idx] == -1 and roll != 6:
        return
    
    if tokens[token_idx] >= 0 and tokens[token_idx] + roll > 57:
        return
    
    if tokens[token_idx] == -1 and roll == 6:
        tokens[token_idx] = 0
        game_state['log'] = f"🚀 {player.upper()} BROUGHT TOKEN OUT!"
    elif tokens[token_idx] >= 0:
        new_pos = tokens[token_idx] + roll
        tokens[token_idx] = 99 if new_pos == 57 else new_pos
        game_state['log'] = f"🎯 {player.upper()} MOVED!"
    
    if 0 <= tokens[token_idx] <= 51 and tokens[token_idx] not in SAFE_POSITIONS:
        my_pos = (game_state['players'][player]['path_start'] + tokens[token_idx]) % 52
        for opp in game_state['active_colors']:
            if opp == player: continue
            opp_tokens = game_state['players'][opp]['tokens']
            for i, pos in enumerate(opp_tokens):
                if 0 <= pos <= 51:
                    opp_pos = (game_state['players'][opp]['path_start'] + pos) % 52
                    if opp_pos == my_pos:
                        opp_tokens[i] = -1
                        captured = True
                        game_state['log'] = f"⚔️ {player.upper()} CAPTURED {opp.upper()}!"
    
    if all(t == 99 for t in tokens):
        game_state['log'] = f"🏆 {player.upper()} WINS! 🎉🎉🎉"
        game_state['game_started'] = False
        socketio.emit('update_state', game_state, room=room_code)
        return
    
    socketio.emit('update_state', game_state, room=room_code)
    
    game_state['rolled_value'] = None
    game_state['can_move'] = False
    
    if roll == 6 or captured:
        game_state['log'] = f"🔄 {player.upper()} GETS EXTRA TURN!"
        socketio.emit('update_state', game_state, room=room_code)
        socketio.sleep(1.5)
        if game_state['mode'] == 'computer' and player != game_state['user_color']:
            socketio.start_background_task(bot_turn, room_code)
    else:
        socketio.sleep(1.2)
        next_turn(room_code)

def next_turn(room_code):
    game_state = game_rooms[room_code]
    
    idx = game_state['turn_order'].index(game_state['turn'])
    game_state['turn'] = game_state['turn_order'][(idx + 1) % len(game_state['turn_order'])]
    game_state['rolled_value'] = None
    game_state['can_move'] = False
    game_state['log'] = f"👉 {game_state['turn'].upper()}'s TURN - CLICK DICE TO ROLL!"
    
    socketio.emit('update_state', game_state, room=room_code)
    
    socketio.sleep(0.8)
    if game_state['mode'] == 'computer' and game_state['turn'] != game_state['user_color']:
        socketio.start_background_task(bot_turn, room_code)

def bot_turn(room_code):
    socketio.sleep(2.0)
    
    if room_code not in game_rooms:
        return
    
    game_state = game_rooms[room_code]
    
    if (game_state['mode'] != 'computer' or 
        game_state['turn'] == game_state['user_color'] or 
        game_state['rolled_value'] is not None):
        return
    
    roll_dice(room_code)

def bot_make_move(room_code):
    socketio.sleep(1.8)
    
    if room_code not in game_rooms:
        return
    
    game_state = game_rooms[room_code]
    
    if (not game_state['can_move'] or 
        game_state['mode'] != 'computer' or 
        game_state['turn'] == game_state['user_color']):
        return
    
    tokens = game_state['players'][game_state['turn']]['tokens']
    roll = game_state['rolled_value']
    
    movable = [i for i, t in enumerate(tokens) 
               if (t == -1 and roll == 6) or (t >= 0 and t + roll <= 57)]
    
    if movable:
        home_tokens = [i for i in movable if tokens[i] == -1]
        if home_tokens and roll == 6:
            chosen = random.choice(home_tokens)
        else:
            chosen = max(movable, key=lambda i: tokens[i] if tokens[i] >= 0 else -100)
        
        move_token(chosen, room_code)

HTML_CODE = """
<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>🎲 Ludo Pro - Production Ready!</title>
    <script src="https://cdn.socket.io/4.5.4/socket.io.min.js"></script>
    <style>
        * {margin:0;padding:0;box-sizing:border-box;}
        :root {--red:#ff4d4d;--green:#2ecc71;--yellow:#f1c40f;--blue:#3498db;--dark:#2c3e50;}
        body {font-family:'Segoe UI',Tahoma,Geneva,Verdana,sans-serif;background:linear-gradient(135deg,#667eea 0%,#764ba2 100%);display:flex;flex-direction:column;align-items:center;padding:20px;color:white;margin:0;min-height:100vh;justify-content:center;}
        
        #main-menu, #color-select, #player-select, #room-menu {text-align:center;display:block;}
        #main-menu h1 {font-size:56px;margin-bottom:40px;text-shadow:3px 3px 6px rgba(0,0,0,0.3);animation:glow 2s ease-in-out infinite alternate;}
        @keyframes glow {from {text-shadow:0 0 20px #fff,0 0 30px #fff,0 0 40px #f39c12;} to {text-shadow:0 0 10px #fff,0 0 20px #f39c12;}}
        .big-btn {background:linear-gradient(135deg,#f39c12,#e67e22);color:white;font-size:32px;font-weight:bold;padding:25px 50px;margin:20px;border:none;border-radius:15px;cursor:pointer;box-shadow:0 10px 20px rgba(0,0,0,0.3);transition:all 0.3s;text-transform:uppercase;letter-spacing:2px;}
        .big-btn:hover {transform:translateY(-5px) scale(1.05);box-shadow:0 15px 30px rgba(0,0,0,0.4);}
        
        .room-code-display {background:rgba(255,255,255,0.2);padding:20px 40px;border-radius:15px;margin:20px auto;font-size:48px;font-weight:900;letter-spacing:8px;box-shadow:0 8px 16px rgba(0,0,0,0.3);border:3px solid rgba(255,255,255,0.4);}
        
        .input-field {font-size:32px;padding:20px;border-radius:10px;border:3px solid rgba(255,255,255,0.3);background:rgba(255,255,255,0.9);color:#2c3e50;font-weight:bold;letter-spacing:4px;text-align:center;text-transform:uppercase;margin:20px;}
        .input-field:focus {outline:none;border-color:#f39c12;box-shadow:0 0 20px rgba(243,156,18,0.5);}
        
        .color-option {display:inline-block;width:120px;height:120px;margin:25px;border-radius:50%;cursor:pointer;border:8px solid rgba(255,255,255,0.3);position:relative;transition:all 0.3s;box-shadow:0 8px 16px rgba(0,0,0,0.2);}
        .color-option:hover {transform:scale(1.1);border-color:rgba(255,215,0,0.6);box-shadow:0 12px 24px rgba(0,0,0,0.3);}
        .color-option.selected {border-color:gold;transform:scale(1.15);box-shadow:0 0 30px rgba(255,215,0,0.6);}
        .color-option.disabled {opacity:0.3;cursor:not-allowed;filter:grayscale(100%);}
        .color-option::after {content:'✓';position:absolute;inset:0;color:white;font-size:70px;display:flex;align-items:center;justify-content:center;opacity:0;font-weight:bold;text-shadow:2px 2px 4px rgba(0,0,0,0.5);}
        .color-option.selected::after {opacity:1;}
        
        .player-option {background:linear-gradient(135deg,#3498db,#2980b9);color:white;font-size:28px;font-weight:bold;padding:35px 70px;margin:25px;border-radius:15px;cursor:pointer;display:inline-block;box-shadow:0 8px 16px rgba(0,0,0,0.3);transition:all 0.3s;text-transform:uppercase;}
        .player-option:hover {transform:translateY(-5px) scale(1.05);box-shadow:0 12px 24px rgba(0,0,0,0.4);}
        
        .player-bar {display:flex;justify-content:space-between;width:700px;margin:12px 0;}
        .status-box {display:flex;align-items:center;background:white;padding:15px 25px;border-radius:15px;gap:15px;cursor:pointer;border:5px solid transparent;transition:all 0.3s;color:var(--dark);box-shadow:0 4px 8px rgba(0,0,0,0.2);font-weight:bold;min-width:160px;justify-content:center;}
        .status-box:hover {transform:translateY(-2px) scale(1.02);box-shadow:0 6px 12px rgba(0,0,0,0.3);}
        .status-box.active {border:5px solid #f1c40f;transform:translateY(-3px) scale(1.05);box-shadow:0 0 30px rgba(241,196,15,0.8);background:#fffef5;}
        .status-box.bot {opacity:0.8;}
        
        .color-indicator {width:28px;height:28px;border-radius:50%;border:3px solid #555;box-shadow:0 2px 4px rgba(0,0,0,0.2);}
        
        .dice-slot {width:70px;height:70px;background:linear-gradient(145deg,#ffffff,#f0f0f0);border-radius:15px;display:flex;align-items:center;justify-content:center;font-size:32px;font-weight:900;border:4px solid #ddd;box-shadow:0 4px 8px rgba(0,0,0,0.2);transition:all 0.2s;cursor:pointer;user-select:none;}
        .dice-slot:hover {transform:scale(1.1);box-shadow:0 6px 12px rgba(0,0,0,0.3);}
        .status-box.active .dice-slot {animation:shakeDice 0.8s infinite;background:linear-gradient(145deg,#fff9cc,#ffe066);border:4px solid #f39c12;box-shadow:0 0 30px rgba(243,156,18,0.8);font-size:24px;cursor:pointer !important;}
        @keyframes shakeDice {0%, 100% {transform:rotate(0deg) scale(1);} 25% {transform:rotate(-5deg) scale(1.05);} 75% {transform:rotate(5deg) scale(1.05);}}
        
        .board {display:grid;grid-template-columns:repeat(15,46px);grid-template-rows:repeat(15,46px);gap:2px;background:#95a5a6;border:15px solid var(--dark);border-radius:12px;box-shadow:0 20px 40px rgba(0,0,0,0.5);}
        .cell {background:#ecf0f1;position:relative;display:flex;align-items:center;justify-content:center;transition:background 0.2s;}
        .cell.safe-zone::after {content:"★";color:#f39c12;font-size:28px;position:absolute;text-shadow:1px 1px 2px rgba(0,0,0,0.2);}
        
        #cell-8-2,#cell-8-3,#cell-8-4,#cell-8-5,#cell-8-6 {background:#ffcccb;}
        #cell-2-8,#cell-3-8,#cell-4-8,#cell-5-8,#cell-6-8 {background:#d5f5e3;}
        #cell-8-14,#cell-8-13,#cell-8-12,#cell-8-11,#cell-8-10 {background:#fcf3cf;}
        #cell-14-8,#cell-13-8,#cell-12-8,#cell-11-8,#cell-10-8 {background:#d6eaf8;}
        
        .yard {grid-row:span 6;grid-column:span 6;display:flex;align-items:center;justify-content:center;transition:opacity 0.3s;}
        .yard.red {background:linear-gradient(135deg,#ff6b6b,#ee5a6f);}
        .yard.green {background:linear-gradient(135deg,#2ecc71,#27ae60);}
        .yard.blue {background:linear-gradient(135deg,#3498db,#2980b9);}
        .yard.yellow {background:linear-gradient(135deg,#f1c40f,#f39c12);}
        .yard.inactive {opacity:0.3;filter:grayscale(80%);}
        .yard-inner {background:rgba(255,255,255,0.95);width:78%;height:78%;border-radius:12px;display:grid;grid-template-columns:1fr 1fr;gap:12px;padding:18px;box-shadow:inset 0 2px 8px rgba(0,0,0,0.1);}
        
        .home-center {grid-column:7/span 3;grid-row:7/span 3;background:conic-gradient(var(--green)0deg 90deg,var(--yellow)90deg 180deg,var(--blue)180deg 270deg,var(--red)270deg 360deg);border-radius:50%;box-shadow:inset 0 0 20px rgba(0,0,0,0.3);}
        
        .token {width:36px;height:36px;border-radius:50% 50% 50% 0;transform:rotate(-45deg);border:3px solid white;box-shadow:0 3px 6px rgba(0,0,0,0.3);z-index:10;cursor:pointer;transition:all 0.2s;}
        .token.red {background:linear-gradient(135deg,#ff4d4d,#c0392b);}
        .token.green {background:linear-gradient(135deg,#2ecc71,#27ae60);}
        .token.yellow {background:linear-gradient(135deg,#f1c40f,#f39c12);}
        .token.blue {background:linear-gradient(135deg,#3498db,#2980b9);}
        .token:hover {transform:rotate(-45deg) scale(1.1);}
        .movable {animation:bounce 0.7s infinite alternate;border-color:gold;border-width:4px;box-shadow:0 0 20px rgba(255,215,0,0.9),0 3px 6px rgba(0,0,0,0.3);}
        @keyframes bounce {from {transform:rotate(-45deg) scale(1);} to {transform:rotate(-45deg) scale(1.25);}}
        
        #status-log {background:linear-gradient(135deg,#1abc9c,#16a085);padding:20px 50px;border-radius:40px;margin:18px 0;font-weight:900;font-size:22px;text-align:center;box-shadow:0 8px 16px rgba(0,0,0,0.3);min-width:650px;text-transform:uppercase;letter-spacing:2px;animation:fadeIn 0.5s;}
        @keyframes fadeIn {from {opacity:0;transform:translateY(-10px);} to {opacity:1;transform:translateY(0);}}
        
        #game-container {display:none;}
        #color-select, #player-select, #room-menu {display:none;}
        h2 {font-size:42px;margin:30px 0;text-shadow:2px 2px 4px rgba(0,0,0,0.3);}
        
        .copy-btn {background:linear-gradient(135deg,#3498db,#2980b9);color:white;font-size:18px;padding:12px 30px;border:none;border-radius:10px;cursor:pointer;margin-top:15px;font-weight:bold;box-shadow:0 4px 8px rgba(0,0,0,0.2);transition:all 0.3s;}
        .copy-btn:hover {transform:translateY(-2px);box-shadow:0 6px 12px rgba(0,0,0,0.3);}
        
        /* Connection status indicator */
        .connection-status {
            position: fixed;
            top: 10px;
            right: 10px;
            background: rgba(0,0,0,0.7);
            color: white;
            padding: 8px 16px;
            border-radius: 20px;
            font-size: 14px;
            z-index: 1000;
        }
        .connection-status.connected {
            background: rgba(46, 204, 113, 0.8);
        }
        .connection-status.disconnected {
            background: rgba(231, 76, 60, 0.8);
        }
    </style>
</head>
<body>
    <div class="connection-status" id="connStatus">Connecting...</div>

    <div id="main-menu">
        <h1>🎲 LUDO PRO 🎲</h1>
        <button class="big-btn" onclick="startComputer()">🤖 VS COMPUTER</button><br>
        <button class="big-btn" onclick="startMultiplayer()">👥 LOCAL MULTIPLAYER</button><br>
        <button class="big-btn" onclick="showOnlineMenu()">🌐 ONLINE MULTIPLAYER</button>
    </div>
    
    <div id="room-menu">
        <h2>🌐 ONLINE MULTIPLAYER</h2>
        <button class="big-btn" onclick="createOnlineRoom()">➕ CREATE ROOM</button><br>
        <h2 style="margin-top:40px;">OR JOIN EXISTING ROOM</h2>
        <input type="text" class="input-field" id="join-code-input" placeholder="ENTER CODE" maxlength="6"><br>
        <button class="big-btn" onclick="joinOnlineRoom()">🚪 JOIN ROOM</button><br>
        <button class="big-btn" style="background:linear-gradient(135deg,#95a5a6,#7f8c8d);margin-top:20px;" onclick="backToMenu()">← BACK</button>
    </div>
    
    <div id="color-select">
        <h2>🎨 SELECT YOUR COLOR</h2>
        <div id="room-code-container" style="display:none;">
            <p style="font-size:24px;margin:20px;">Share this code with friends:</p>
            <div class="room-code-display" id="room-code-display"></div>
            <button class="copy-btn" onclick="copyRoomCode()">📋 COPY CODE</button>
        </div>
        <div style="margin:60px;">
            <div class="color-option" style="background:var(--red);" data-color="red"></div>
            <div class="color-option" style="background:var(--green);" data-color="green"></div><br>
            <div class="color-option" style="background:var(--blue);" data-color="blue"></div>
            <div class="color-option" style="background:var(--yellow);" data-color="yellow"></div>
        </div>
    </div>
    
    <div id="player-select">
        <h2>👥 SELECT NUMBER OF PLAYERS</h2>
        <div class="player-option" onclick="confirmGame(2)">2 PLAYERS</div><br>
        <div class="player-option" onclick="confirmGame(4)">4 PLAYERS</div>
    </div>
    
    <div id="game-container">
        <div id="status-log">🎮 READY TO PLAY!</div>
        <div class="player-bar">
            <div id="box-red" class="status-box">
                <div class="color-indicator" style="background:var(--red);"></div>
                <div class="dice-slot" id="dice-red">-</div>
            </div>
            <div id="box-green" class="status-box">
                <div class="dice-slot" id="dice-green">-</div>
                <div class="color-indicator" style="background:var(--green);"></div>
            </div>
        </div>
        <div class="board" id="board">
            <div class="yard red" style="grid-area:1/1/7/7;"><div class="yard-inner" id="yard-red"></div></div>
            <div class="yard green" style="grid-area:1/10/7/16;"><div class="yard-inner" id="yard-green"></div></div>
            <div class="yard blue" style="grid-area:10/1/16/7;"><div class="yard-inner" id="yard-blue"></div></div>
            <div class="yard yellow" style="grid-area:10/10/16/16;"><div class="yard-inner" id="yard-yellow"></div></div>
            <div class="home-center"></div>
        </div>
        <div class="player-bar" style="margin-top:15px;">
            <div id="box-blue" class="status-box">
                <div class="color-indicator" style="background:var(--blue);"></div>
                <div class="dice-slot" id="dice-blue">-</div>
            </div>
            <div id="box-yellow" class="status-box">
                <div class="dice-slot" id="dice-yellow">-</div>
                <div class="color-indicator" style="background:var(--yellow);"></div>
            </div>
        </div>
    </div>
    
    <script>
        const socket = io({
            transports: ['websocket', 'polling'],
            upgrade: true,
            rememberUpgrade: true,
            timeout: 10000,
            reconnection: true,
            reconnectionDelay: 1000,
            reconnectionAttempts: 5
        });
        
        let gameMode = null;
        let selectedColor = null;
        let currentRoomCode = null;
        let isOnlineMode = false;
        
        const connStatus = document.getElementById('connStatus');
        
        socket.on('connect', () => {
            console.log('✅ Connected to server');
            connStatus.textContent = '✅ Connected';
            connStatus.className = 'connection-status connected';
        });
        
        socket.on('disconnect', () => {
            console.log('❌ Disconnected from server');
            connStatus.textContent = '❌ Disconnected';
            connStatus.className = 'connection-status disconnected';
        });
        
        socket.on('connect_error', (error) => {
            console.error('Connection error:', error);
            connStatus.textContent = '⚠️ Connection Error';
            connStatus.className = 'connection-status disconnected';
        });
        
        socket.on('error', (data) => {
            alert(data.message);
        });
        
        socket.on('room_joined', (data) => {
            console.log('✅ Joined room:', data);
            currentRoomCode = data.room_code;
        });
        
        socket.on('room_assigned', (data) => {
            console.log('📍 Room assigned:', data.room_code);
            currentRoomCode = data.room_code;
        });
        
        const pathCoords = [[7,2],[7,3],[7,4],[7,5],[7,6],[6,7],[5,7],[4,7],[3,7],[2,7],[1,7],[1,8],[1,9],[2,9],[3,9],[4,9],[5,9],[6,9],[7,10],[7,11],[7,12],[7,13],[7,14],[7,15],[8,15],[9,15],[9,14],[9,13],[9,12],[9,11],[9,10],[10,9],[11,9],[12,9],[13,9],[14,9],[15,9],[15,8],[15,7],[14,7],[13,7],[12,7],[11,7],[10,7],[9,6],[9,5],[9,4],[9,3],[9,2],[9,1],[8,1],[7,1]];
        const homePaths = {
            red:[[8,2],[8,3],[8,4],[8,5],[8,6],[8,7]],
            green:[[2,8],[3,8],[4,8],[5,8],[6,8],[7,8]],
            yellow:[[8,14],[8,13],[8,12],[8,11],[8,10],[8,9]],
            blue:[[14,8],[13,8],[12,8],[11,8],[10,8],[9,8]]
        };
        const safeCoords = ["7-2","2-7","6-9","9-14","14-9","9-2","7-14","2-9"];
        
        // Initialize board
        for(let r=1;r<=15;r++) {
            for(let c=1;c<=15;c++) {
                if(!((r<=6&&c<=6)||(r<=6&&c>=10)||(r>=10&&c<=6)||(r>=10&&c>=10)||(r>=7&&r<=9&&c>=7&&c<=9))) {
                    let cell=document.createElement('div');
                    cell.className='cell';
                    cell.id=`cell-${r}-${c}`;
                    if(safeCoords.includes(`${r}-${c}`)) cell.classList.add('safe-zone');
                    cell.style.gridRow=r;
                    cell.style.gridColumn=c;
                    document.getElementById('board').appendChild(cell);
                }
            }
        }
        
        function backToMenu() {
            document.getElementById('room-menu').style.display='none';
            document.getElementById('main-menu').style.display='block';
        }
        
        function showOnlineMenu() {
            document.getElementById('main-menu').style.display='none';
            document.getElementById('room-menu').style.display='block';
            isOnlineMode = true;
        }
        
        async function createOnlineRoom() {
            const response = await fetch('/api/create-room', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({mode: 'multiplayer', num_players: 4})
            });
            
            const data = await response.json();
            if(data.success) {
                currentRoomCode = data.room_code;
                gameMode = 'multiplayer';
                
                document.getElementById('room-menu').style.display='none';
                document.getElementById('color-select').style.display='block';
                document.getElementById('room-code-container').style.display='block';
                document.getElementById('room-code-display').innerText = data.room_code;
                
                console.log('✅ Room created:', data.room_code);
            }
        }
        
        async function joinOnlineRoom() {
            const code = document.getElementById('join-code-input').value.toUpperCase().trim();
            if(!code) {
                alert('Please enter a room code!');
                return;
            }
            
            const response = await fetch(`/api/join-room/${code}`);
            const data = await response.json();
            
            if(data.success && data.exists) {
                currentRoomCode = code;
                gameMode = 'multiplayer';
                
                document.getElementById('room-menu').style.display='none';
                document.getElementById('color-select').style.display='block';
                
                document.querySelectorAll('.color-option').forEach(option => {
                    const color = option.getAttribute('data-color');
                    if(!data.available_colors.includes(color)) {
                        option.classList.add('disabled');
                        option.style.pointerEvents = 'none';
                    }
                });
                
                console.log('✅ Joining room:', code);
            } else {
                alert('Room not found! Please check the code.');
            }
        }
        
        function copyRoomCode() {
            const code = document.getElementById('room-code-display').innerText;
            navigator.clipboard.writeText(code);
            alert('Room code copied: ' + code);
        }
        
        document.querySelectorAll('.color-option').forEach(option => {
            option.addEventListener('click', function() {
                if(this.classList.contains('disabled')) return;
                
                document.querySelectorAll('.color-option').forEach(el => el.classList.remove('selected'));
                this.classList.add('selected');
                selectedColor = this.getAttribute('data-color');
                console.log('🎨 Selected color:', selectedColor);
                
                setTimeout(() => {
                    if(isOnlineMode && currentRoomCode) {
                        socket.emit('join_room_with_code', {
                            room_code: currentRoomCode,
                            color: selectedColor
                        });
                        
                        document.getElementById('color-select').style.display='none';
                        document.getElementById('game-container').style.display='block';
                        
                        socket.emit('start_game', {
                            mode: 'multiplayer',
                            num_players: 4,
                            room_code: currentRoomCode
                        });
                    } else {
                        document.getElementById('color-select').style.display='none';
                        document.getElementById('player-select').style.display='block';
                    }
                }, 500);
            });
        });
        
        function startComputer() {
            console.log('🤖 Starting VS COMPUTER mode');
            gameMode = 'computer';
            isOnlineMode = false;
            document.getElementById('main-menu').style.display='none';
            document.getElementById('color-select').style.display='block';
        }
        
        function startMultiplayer() {
            console.log('👥 Starting LOCAL MULTIPLAYER mode');
            gameMode = 'multiplayer';
            isOnlineMode = false;
            document.getElementById('main-menu').style.display='none';
            document.getElementById('player-select').style.display='block';
        }
        
        function confirmGame(players) {
            console.log('✅ Starting game:', {mode: gameMode, players, color: selectedColor, room: currentRoomCode});
            document.getElementById('player-select').style.display='none';
            document.getElementById('game-container').style.display='block';
            
            socket.emit('start_game', {
                mode: gameMode,
                num_players: players,
                user_color: gameMode === 'computer' ? selectedColor : null,
                room_code: currentRoomCode
            });
        }
        
        document.querySelectorAll('.status-box').forEach(box => {
            box.addEventListener('click', function() {
                console.log('🎲 DICE BOX CLICKED! Room:', currentRoomCode);
                socket.emit('roll_dice', {room_code: currentRoomCode});
            });
        });
        
        document.querySelectorAll('.dice-slot').forEach(dice => {
            dice.addEventListener('click', function(e) {
                e.stopPropagation();
                console.log('🎲 DICE SLOT CLICKED! Room:', currentRoomCode);
                socket.emit('roll_dice', {room_code: currentRoomCode});
            });
        });
        
        socket.on('update_state', (state) => {
            console.log('📊 STATE UPDATE:', state.log);
            
            document.getElementById('status-log').innerText = state.log;
            
            ['red','green','yellow','blue'].forEach(color => {
                const yard = document.querySelector(`.yard.${color}`);
                const box = document.getElementById(`box-${color}`);
                const dice = document.getElementById(`dice-${color}`);
                
                yard.classList.toggle('inactive', !state.active_colors.includes(color));
                box.classList.remove('active','bot');
                dice.innerText = '-';
                
                if(state.turn === color && state.active_colors.includes(color)) {
                    box.classList.add('active');
                    if(state.rolled_value !== null) {
                        dice.innerText = state.rolled_value;
                    } else {
                        dice.innerText = (gameMode === 'computer' && color !== state.user_color) ? '🤖' : '🎲';
                    }
                    if(gameMode === 'computer' && color !== state.user_color) {
                        box.classList.add('bot');
                    }
                }
            });
            
            document.querySelectorAll('.token').forEach(e => e.remove());
            
            ['red','green','yellow','blue'].forEach(color => {
                if(!state.active_colors.includes(color)) return;
                
                state.players[color].tokens.forEach((pos, idx) => {
                    if(pos === 99) return;
                    
                    let token = document.createElement('div');
                    token.className = `token ${color}`;
                    
                    if(state.turn === color && state.can_move && 
                       (gameMode === 'multiplayer' || color === state.user_color || !isOnlineMode)) {
                        const roll = state.rolled_value;
                        if((pos === -1 && roll === 6) || (pos >= 0 && pos + roll <= 57)) {
                            token.classList.add('movable');
                            token.onclick = () => {
                                console.log(`🎯 Token ${idx} clicked. Room: ${currentRoomCode}`);
                                socket.emit('move_token', {
                                    token_index: idx,
                                    room_code: currentRoomCode
                                });
                            };
                        }
                    }
                    
                    if(pos === -1) {
                        document.getElementById(`yard-${color}`).appendChild(token);
                    } else if(pos >= 52) {
                        let step = pos - 52;
                        let coords = homePaths[color][step];
                        if(coords) {
                            const cell = document.getElementById(`cell-${coords[0]}-${coords[1]}`);
                            if(cell) cell.appendChild(token);
                        }
                    } else {
                        let actualIdx = (state.players[color].path_start + pos) % 52;
                        let coords = pathCoords[actualIdx];
                        if(coords) {
                            const cell = document.getElementById(`cell-${coords[0]}-${coords[1]}`);
                            if(cell) cell.appendChild(token);
                        }
                    }
                });
            });
        });
    </script>
</body>
</html>
"""

if __name__ == '__main__':
    port = int(os.getenv('PORT', 5000))
    print(f"🚀 LUDO SERVER - PRODUCTION MODE")
    print("=" * 60)
    print(f"🌐 Server: http://0.0.0.0:{port}")
    print("✅ All Modes Working")
    print("=" * 60)
    # Use eventlet for production
    socketio.run(app, host='0.0.0.0', port=port, debug=False)
