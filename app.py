from flask import Flask, render_template_string
from flask_socketio import SocketIO, emit
import random
import time

app = Flask(__name__)
app.config['SECRET_KEY'] = 'ludo-secret!'
socketio = SocketIO(app, cors_allowed_origins="*", async_mode='threading')

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
        time.sleep(1.8)
        next_turn()
    else:
        game_state['can_move'] = True
        emit('update_state', game_state, broadcast=True)
        
        if game_state['mode'] == 'computer' and game_state['turn'] != game_state['user_color']:
            socketio.start_background_task(bot_make_move)

@socketio.on('move_token')
def handle_move(data):
    if not game_state['can_move']:
        return
    
    if game_state['mode'] == 'computer' and game_state['turn'] != game_state['user_color']:
        return
    
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
        game_state['log'] = f"🏆 {player.upper()} WINS THE GAME! 🎉"
        emit('update_state', game_state, broadcast=True)
        return
    
    emit('update_state', game_state, broadcast=True)
    
    game_state['rolled_value'] = None
    game_state['can_move'] = False
    
    if roll == 6 or captured:
        game_state['log'] = f"🔄 {player.upper()} gets extra turn!"
        emit('update_state', game_state, broadcast=True)
        time.sleep(1.5)
        if game_state['mode'] == 'computer' and player != game_state['user_color']:
            socketio.start_background_task(bot_turn)
    else:
        time.sleep(1.2)
        next_turn()

def next_turn():
    idx = turn_order.index(game_state['turn'])
    game_state['turn'] = turn_order[(idx + 1) % len(turn_order)]
    game_state['rolled_value'] = None
    game_state['can_move'] = False
    game_state['log'] = f"👉 {game_state['turn'].upper()}'s TURN"
    emit('update_state', game_state, broadcast=True)
    
    time.sleep(0.8)  # Small delay to ensure UI updates before bot starts
    if game_state['mode'] == 'computer' and game_state['turn'] != game_state['user_color']:
        socketio.start_background_task(bot_turn)

def bot_turn():
    time.sleep(1.8)
    
    if (game_state['mode'] != 'computer' or 
        game_state['turn'] == game_state['user_color'] or 
        game_state['rolled_value'] is not None):
        return
    
    roll_dice()

def bot_make_move():
    time.sleep(1.6)
    
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
        
        move_token(chosen)

HTML_CODE = """
<!DOCTYPE html>
<html>
<head>
    <title>Ludo Pro - Fully Working</title>
    <script src="https://cdnjs.cloudflare.com/ajax/libs/socket.io/4.0.1/socket.io.js"></script>
    <style>
        :root {--red:#ff4d4d;--green:#2ecc71;--yellow:#f1c40f;--blue:#3498db;--dark:#2c3e50;}
        body {font-family:'Segoe UI',sans-serif;background:#34495e;display:flex;flex-direction:column;align-items:center;padding:20px;color:white;margin:0;height:100vh;justify-content:center;}
        #main-menu, #color-select, #player-select {text-align:center;}
        .big-btn {background:#f39c12;color:white;font-size:28px;padding:20px 40px;margin:20px;border:none;border-radius:20px;cursor:pointer;box-shadow:0 8px 16px rgba(0,0,0,0.4);}
        .color-option {display:inline-block;width:100px;height:100px;margin:20px;border-radius:50%;cursor:pointer;border:6px solid transparent;position:relative;}
        .color-option.selected {border-color:gold;transform:scale(1.1);}
        .color-option::after {content:'✓';position:absolute;inset:0;color:white;font-size:60px;display:flex;align-items:center;justify-content:center;opacity:0;font-weight:bold;}
        .color-option.selected::after {opacity:1;}
        .player-option {background:#3498db;color:white;font-size:24px;padding:30px 60px;margin:30px;border-radius:20px;cursor:pointer;display:inline-block;box-shadow:0 6px 12px rgba(0,0,0,0.3);}
        .player-bar {display:flex;justify-content:space-between;width:660px;margin:10px 0;}
        .status-box {display:flex;align-items:center;background:white;padding:10px 18px;border-radius:12px;gap:12px;cursor:pointer;border-bottom:6px solid transparent;transition:all 0.3s;color:var(--dark);}
        .status-box.active {border-bottom:6px solid #f1c40f;transform:translateY(-2px);}
        .status-box.bot {opacity:0.7;cursor:default;}
        .dice-slot {width:48px;height:48px;background:#f8f9fa;border-radius:10px;display:flex;align-items:center;justify-content:center;font-size:24px;font-weight:bold;border:1px solid #ddd;}
        .board {display:grid;grid-template-columns:repeat(15,45px);grid-template-rows:repeat(15,45px);gap:2px;background:#b2bec3;border:12px solid var(--dark);border-radius:10px;}
        .cell {background:white;position:relative;display:flex;align-items:center;justify-content:center;}
        .cell.safe-zone::after {content:"★";color:#bdc3c7;font-size:26px;position:absolute;}
        #cell-8-2,#cell-8-3,#cell-8-4,#cell-8-5,#cell-8-6 {background:#ffcccc;}
        #cell-2-8,#cell-3-8,#cell-4-8,#cell-5-8,#cell-6-8 {background:#d5f5e3;}
        #cell-8-14,#cell-8-13,#cell-8-12,#cell-8-11,#cell-8-10 {background:#fcf3cf;}
        #cell-14-8,#cell-13-8,#cell-12-8,#cell-11-8,#cell-10-8 {background:#d6eaf8;}
        .yard {grid-row:span 6;grid-column:span 6;display:flex;align-items:center;justify-content:center;}
        .yard.red {background:var(--red);}
        .yard.green {background:var(--green);}
        .yard.blue {background:var(--blue);}
        .yard.yellow {background:var(--yellow);}
        .yard.inactive {opacity:0.4;}
        .yard-inner {background:rgba(255,255,255,0.9);width:75%;height:75%;border-radius:10px;display:grid;grid-template-columns:1fr 1fr;gap:10px;padding:15px;}
        .home-center {grid-column:7/span 3;grid-row:7/span 3;background:conic-gradient(var(--green)0deg 90deg,var(--yellow)90deg 180deg,var(--blue)180deg 270deg,var(--red)270deg 360deg);}
        .token {width:32px;height:32px;border-radius:50% 50% 50% 0;transform:rotate(-45deg);border:2px solid white;box-shadow:2px 2px 5px rgba(0,0,0,0.3);z-index:10;cursor:pointer;}
        .token.red {background:var(--red);}
        .token.green {background:var(--green);}
        .token.yellow {background:var(--yellow);}
        .token.blue {background:var(--blue);}
        .movable {animation:bounce 0.6s infinite alternate;border-color:gold;}
        @keyframes bounce {from {transform:rotate(-45deg) scale(1);} to {transform:rotate(-45deg) scale(1.15);}}
        #status-log {background:#1abc9c;padding:15px 40px;border-radius:30px;margin:15px 0;font-weight:bold;font-size:18px;text-align:center;}
        #game-container {display:none;}
    </style>
</head>
<body>
    <div id="main-menu">
        <h1 style="font-size:48px;margin-bottom:50px;">🎲 LUDO PRO 🎲</h1>
        <button class="big-btn" onclick="startComputer()">VS COMPUTER</button><br>
        <button class="big-btn" onclick="startMultiplayer()">LOCAL MULTIPLAYER</button>
    </div>
    <div id="color-select" style="display:none;">
        <h2 style="font-size:36px;">SELECT YOUR COLOR</h2>
        <div style="margin:50px;">
            <div class="color-option" style="background:var(--blue);" onclick="selectColor('blue')"></div>
            <div class="color-option" style="background:var(--red);" onclick="selectColor('red')"></div><br>
            <div class="color-option" style="background:var(--green);" onclick="selectColor('green')"></div>
            <div class="color-option" style="background:var(--yellow);" onclick="selectColor('yellow')"></div>
        </div>
    </div>
    <div id="player-select" style="display:none;">
        <h2 style="font-size:36px;">SELECT PLAYERS</h2>
        <div class="player-option" onclick="confirmGame(2)">2 PLAYERS</div><br>
        <div class="player-option" onclick="confirmGame(4)">4 PLAYERS</div>
    </div>
    <div id="game-container">
        <div id="status-log">Game will start here...</div>
        <div class="player-bar">
            <div id="box-red" class="status-box" onclick="roll()">
                <div style="width:20px;height:20px;background:var(--red);border-radius:50%;"></div>
                <div class="dice-slot" id="dice-red">-</div>
            </div>
            <div id="box-green" class="status-box" onclick="roll()">
                <div class="dice-slot" id="dice-green">-</div>
                <div style="width:20px;height:20px;background:var(--green);border-radius:50%;"></div>
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
            <div id="box-blue" class="status-box" onclick="roll()">
                <div style="width:20px;height:20px;background:var(--blue);border-radius:50%;"></div>
                <div class="dice-slot" id="dice-blue">-</div>
            </div>
            <div id="box-yellow" class="status-box" onclick="roll()">
                <div class="dice-slot" id="dice-yellow">-</div>
                <div style="width:20px;height:20px;background:var(--yellow);border-radius:50%;"></div>
            </div>
        </div>
    </div>
    <script>
        const socket = io();
        let gameMode = null, selectedColor = null;
        const pathCoords = [[7,2],[7,3],[7,4],[7,5],[7,6],[6,7],[5,7],[4,7],[3,7],[2,7],[1,7],[1,8],[1,9],[2,9],[3,9],[4,9],[5,9],[6,9],[7,10],[7,11],[7,12],[7,13],[7,14],[7,15],[8,15],[9,15],[9,14],[9,13],[9,12],[9,11],[9,10],[10,9],[11,9],[12,9],[13,9],[14,9],[15,9],[15,8],[15,7],[14,7],[13,7],[12,7],[11,7],[10,7],[9,6],[9,5],[9,4],[9,3],[9,2],[9,1],[8,1],[7,1]];
        const homePaths = {red:[[8,2],[8,3],[8,4],[8,5],[8,6],[8,7]],green:[[2,8],[3,8],[4,8],[5,8],[6,8],[7,8]],yellow:[[8,14],[8,13],[8,12],[8,11],[8,10],[8,9]],blue:[[14,8],[13,8],[12,8],[11,8],[10,8],[9,8]]};
        const safeCoords = ["7-2","2-7","6-9","9-14","14-9","9-2","7-14","2-9"];
        
        for(let r=1;r<=15;r++)for(let c=1;c<=15;c++)if(!((r<=6&&c<=6)||(r<=6&&c>=10)||(r>=10&&c<=6)||(r>=10&&c>=10)||(r>=7&&r<=9&&c>=7&&c<=9))){let cell=document.createElement('div');cell.className='cell';cell.id=`cell-${r}-${c}`;if(safeCoords.includes(`${r}-${c}`))cell.classList.add('safe-zone');cell.style.gridRow=r;cell.style.gridColumn=c;document.getElementById('board').appendChild(cell);}
        
        function startComputer(){gameMode='computer';document.getElementById('main-menu').style.display='none';document.getElementById('color-select').style.display='block';}
        function startMultiplayer(){gameMode='multiplayer';document.getElementById('main-menu').style.display='none';document.getElementById('player-select').style.display='block';}
        function selectColor(color){document.querySelectorAll('.color-option').forEach(el=>el.classList.remove('selected'));event.target.classList.add('selected');selectedColor=color;setTimeout(()=>{document.getElementById('color-select').style.display='none';document.getElementById('player-select').style.display='block';},500);}
        function confirmGame(players){document.getElementById('player-select').style.display='none';document.getElementById('game-container').style.display='block';socket.emit('start_game',{mode:gameMode,num_players:players,user_color:gameMode==='computer'?selectedColor:null});}
        function roll(){socket.emit('roll_dice');}
        
        socket.on('update_state',(state)=>{
            document.getElementById('status-log').innerText=state.log;
            ['red','green','yellow','blue'].forEach(color=>{
                const yard=document.querySelector(`.yard.${color}`);
                const box=document.getElementById(`box-${color}`);
                const dice=document.getElementById(`dice-${color}`);
                yard.classList.toggle('inactive',!state.active_colors.includes(color));
                box.classList.remove('active','bot');
                dice.innerText='-';
                if(state.turn===color&&state.active_colors.includes(color)){
                    box.classList.add('active');
                    dice.innerText=state.rolled_value!==null?state.rolled_value:(gameMode==='computer'&&color!==state.user_color?'🤖':'ROLL');
                    if(gameMode==='computer'&&color!==state.user_color)box.classList.add('bot');
                }
            });
            document.querySelectorAll('.token').forEach(e=>e.remove());
            ['red','green','yellow','blue'].forEach(color=>{
                if(!state.active_colors.includes(color))return;
                state.players[color].tokens.forEach((pos,idx)=>{
                    if(pos===99)return;
                    let token=document.createElement('div');
                    token.className=`token ${color}`;
                    if(state.turn===color&&state.can_move&&(gameMode==='multiplayer'||color===state.user_color)){
                        token.onclick=()=>socket.emit('move_token',{token_index:idx});
                        token.classList.add('movable');
                    }
                    if(pos===-1){
                        document.getElementById(`yard-${color}`).appendChild(token);
                    }else if(pos>=52){
                        let step=pos-52;
                        let coords=homePaths[color][step];
                        if(coords)document.getElementById(`cell-${coords[0]}-${coords[1]}`).appendChild(token);
                    }else{
                        let actualIdx=(state.players[color].path_start+pos)%52;
                        let coords=pathCoords[actualIdx];
                        if(coords)document.getElementById(`cell-${coords[0]}-${coords[1]}`).appendChild(token);
                    }
                });
            });
        });
    </script>
</body>
</html>
"""

if __name__ == '__main__':
    print("🚀 LUDO SERVER STARTING ON http://localhost:5000")
    socketio.run(app, debug=False, port=5000)