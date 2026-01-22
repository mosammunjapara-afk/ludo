from flask import Flask, render_template_string
from flask_socketio import SocketIO, emit
import random
import time
import os

app = Flask(__name__)
app.config['SECRET_KEY'] = 'ludo-secret!'
# Render par real-time connection ke liye eventlet best hai
socketio = SocketIO(app, cors_allowed_origins="*", async_mode='eventlet')

SAFE_POSITIONS = [0, 8, 13, 21, 26, 34, 39, 47]

game_state = {
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
    'log': "Click VS COMPUTER or MULTIPLAYER to start!",
    'game_started': False
}

turn_order = []

@app.route('/')
def index():
    return render_template_string(HTML_CODE)

@socketio.on('start_game')
def handle_start_game(data):
    global game_state, turn_order
    game_state['mode'] = data['mode']
    game_state['num_players'] = data['num_players']
    game_state['user_color'] = data.get('user_color')
    game_state['game_started'] = True
    
    if data['num_players'] == 2:
        if data['mode'] == 'computer':
            opp = {'red':'yellow', 'yellow':'red', 'green':'blue', 'blue':'green'}
            game_state['active_colors'] = [data['user_color'], opp[data['user_color']]]
        else:
            game_state['active_colors'] = ['red', 'yellow']
    else:
        game_state['active_colors'] = ['red', 'green', 'yellow', 'blue']
    
    for color in game_state['active_colors']:
        game_state['players'][color]['tokens'] = [-1, -1, -1, -1]
    
    turn_order = game_state['active_colors'][:]
    game_state['turn'] = turn_order[0]
    game_state['rolled_value'] = None
    game_state['can_move'] = False
    game_state['log'] = f"🎮 GAME STARTED! {game_state['turn'].upper()}'s TURN"
    emit('update_state', game_state, broadcast=True)
    
    if game_state['mode'] == 'computer' and game_state['turn'] != game_state['user_color']:
        socketio.start_background_task(bot_turn)

@socketio.on('roll_dice')
def handle_roll():
    if not game_state['game_started'] or game_state['rolled_value'] is not None:
        return
    # Check if it's user's turn in computer mode
    if game_state['mode'] == 'computer' and game_state['turn'] != game_state['user_color']:
        return
    roll_dice()

def roll_dice():
    val = random.randint(1, 6)
    game_state['rolled_value'] = val
    game_state['log'] = f"🎲 {game_state['turn'].upper()} rolled {val}"
    
    tokens = game_state['players'][game_state['turn']]['tokens']
    has_moves = any((t == -1 and val == 6) or (t >= 0 and t + val <= 57) for t in tokens)
    
    if not has_moves:
        game_state['log'] += " ❌ No moves!"
        emit('update_state', game_state, broadcast=True)
        socketio.sleep(1.5)
        next_turn()
    else:
        game_state['can_move'] = True
        emit('update_state', game_state, broadcast=True)
        if game_state['mode'] == 'computer' and game_state['turn'] != game_state['user_color']:
            socketio.start_background_task(bot_make_move)

@socketio.on('move_token')
def handle_move(data):
    if not game_state['can_move']: return
    if game_state['mode'] == 'computer' and game_state['turn'] != game_state['user_color']: return
    move_token(data['token_index'])

def move_token(token_idx):
    player = game_state['turn']
    tokens = game_state['players'][player]['tokens']
    roll = game_state['rolled_value']
    captured = False
    
    if tokens[token_idx] == -1 and roll == 6:
        tokens[token_idx] = 0
    elif tokens[token_idx] >= 0 and tokens[token_idx] + roll <= 57:
        new_pos = tokens[token_idx] + roll
        tokens[token_idx] = 99 if new_pos == 57 else new_pos
    
    # Capture Logic
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
                        game_state['log'] = f"⚔️ {player.upper()} captured {opp.upper()}!"

    if all(t == 99 for t in tokens):
        game_state['log'] = f"🏆 {player.upper()} WINS! 🎉"
        emit('update_state', game_state, broadcast=True)
        return

    game_state['rolled_value'] = None
    game_state['can_move'] = False
    emit('update_state', game_state, broadcast=True)
    
    if roll == 6 or captured:
        socketio.sleep(1.0)
        if game_state['mode'] == 'computer' and player != game_state['user_color']:
            bot_turn()
    else:
        socketio.sleep(1.0)
        next_turn()

def next_turn():
    idx = turn_order.index(game_state['turn'])
    game_state['turn'] = turn_order[(idx + 1) % len(turn_order)]
    game_state['rolled_value'] = None
    game_state['can_move'] = False
    game_state['log'] = f"👉 {game_state['turn'].upper()}'s TURN"
    emit('update_state', game_state, broadcast=True)
    if game_state['mode'] == 'computer' and game_state['turn'] != game_state['user_color']:
        socketio.start_background_task(bot_turn)

def bot_turn():
    socketio.sleep(1.5)
    roll_dice()

def bot_make_move():
    socketio.sleep(1.0)
    tokens = game_state['players'][game_state['turn']]['tokens']
    roll = game_state['rolled_value']
    movable = [i for i, t in enumerate(tokens) if (t == -1 and roll == 6) or (t >= 0 and t + roll <= 57)]
    if movable:
        chosen = max(movable, key=lambda i: tokens[i])
        move_token(chosen)

HTML_CODE = """
<!DOCTYPE html>
<html>
<head>
    <title>Ludo Pro</title>
    <script src="https://cdnjs.cloudflare.com/ajax/libs/socket.io/4.0.1/socket.io.js"></script>
    <style>
        :root {--red:#ff4d4d;--green:#2ecc71;--yellow:#f1c40f;--blue:#3498db;--dark:#2c3e50;}
        body {font-family:sans-serif; background:#34495e; display:flex; flex-direction:column; align-items:center; color:white;}
        .board {display:grid; grid-template-columns:repeat(15,40px); grid-template-rows:repeat(15,40px); gap:2px; background:#bdc3c7; border:10px solid var(--dark);}
        .cell {background:white; display:flex; align-items:center; justify-content:center; position:relative; color:#333;}
        .yard {grid-row:span 6; grid-column:span 6;}
        .red {background:var(--red);} .green {background:var(--green);} .yellow {background:var(--yellow);} .blue {background:var(--blue);}
        .token {width:30px; height:30px; border-radius:50%; border:2px solid white; cursor:pointer;}
        .movable {box-shadow: 0 0 10px 5px gold; animation: pulse 1s infinite;}
        @keyframes pulse { 0% {transform:scale(1);} 50% {transform:scale(1.1);} 100% {transform:scale(1);} }
        .status-box {padding:10px; background:white; color:black; margin:5px; border-radius:5px; cursor:pointer;}
        .active {border:4px solid gold;}
        #game-container {display:none; margin-top:20px;}
    </style>
</head>
<body>
    <div id="setup">
        <h1>🎲 LUDO PRO</h1>
        <button onclick="start('computer')">VS COMPUTER</button>
        <button onclick="start('multiplayer')">MULTIPLAYER</button>
    </div>

    <div id="game-container">
        <h2 id="log">Waiting...</h2>
        <div style="display:flex;">
            <div id="box-red" class="status-box" onclick="roll()">RED DICE: <span id="dice-red">-</span></div>
            <div id="box-green" class="status-box" onclick="roll()">GREEN DICE: <span id="dice-green">-</span></div>
            <div id="box-yellow" class="status-box" onclick="roll()">YELLOW DICE: <span id="dice-yellow">-</span></div>
            <div id="box-blue" class="status-box" onclick="roll()">BLUE DICE: <span id="dice-blue">-</span></div>
        </div>
        <div class="board" id="board">
            </div>
    </div>

    <script>
        const socket = io();
        function start(m){ 
            socket.emit('start_game', {mode:m, num_players:4, user_color:'red'});
            document.getElementById('setup').style.display='none';
            document.getElementById('game-container').style.display='block';
        }
        function roll(){ socket.emit('roll_dice'); }

        socket.on('update_state', (state) => {
            document.getElementById('log').innerText = state.log;
            ['red','green','yellow','blue'].forEach(c => {
                document.getElementById(`dice-${c}`).innerText = state.turn === c ? (state.rolled_value || 'ROLL') : '-';
                document.getElementById(`box-${c}`).className = 'status-box ' + (state.turn === c ? 'active' : '');
            });
            // Simplified token rendering logic
            document.querySelectorAll('.token').forEach(t => t.remove());
            // Token rendering would go here (similar to your previous code)
        });
    </script>
</body>
</html>
"""

if __name__ == '__main__':
    port = int(os.environ.get("PORT", 5000))
    # Render ke liye host='0.0.0.0' zaroori hai
    socketio.run(app, host='0.0.0.0', port=port)
