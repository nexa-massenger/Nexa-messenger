'use strict';
const http=require('node:http');
const fs=require('node:fs');
const path=require('node:path');
const crypto=require('node:crypto');
const {URL}=require('node:url');
const ROOT=__dirname, PUB=path.join(ROOT,'public'), DATA_DIR=process.env.DATA_DIR||path.join(ROOT,'data'), DATA=path.join(DATA_DIR,'db.json');
fs.mkdirSync(DATA_DIR,{recursive:true});
const ALLOWED_ORIGINS=(process.env.ALLOWED_ORIGINS||'https://localhost,capacitor://localhost').split(',').map(x=>x.trim()).filter(Boolean);
const PORT=Number(process.env.PORT||3000), HOST=process.env.HOST||'0.0.0.0';
const MAX_BODY=64*1024, RATE_WINDOW=60_000, RATE_MAX=100;
let db={users:[],sessions:[],chats:[],messages:[]};
try{if(fs.existsSync(DATA))db={...db,...JSON.parse(fs.readFileSync(DATA,'utf8'))};}catch(e){console.error('Database read failed:',e.message);process.exit(1)}
function save(){const tmp=DATA+'.tmp';fs.writeFileSync(tmp,JSON.stringify(db,null,2),{mode:0o600});fs.renameSync(tmp,DATA);}
const now=()=>Date.now(); const id=()=>crypto.randomUUID();
const hashPassword=(p,salt=crypto.randomBytes(16).toString('hex'))=>({salt,hash:crypto.scryptSync(p,salt,64).toString('hex')});
function verifyPassword(p,u){const h=crypto.scryptSync(p,u.salt,64);return crypto.timingSafeEqual(h,Buffer.from(u.passwordHash,'hex'));}
function safeUser(u){return {id:u.id,username:u.username,displayName:u.displayName,createdAt:u.createdAt};}
function tokenUser(token){const s=db.sessions.find(x=>x.token===token&&x.expiresAt>now());return s?db.users.find(u=>u.id===s.userId):null;}
function tokenFrom(req){const h=req.headers.authorization||'';return h.startsWith('Bearer ')?h.slice(7):'';}
function json(res,status,obj){const b=JSON.stringify(obj);res.writeHead(status,{'Content-Type':'application/json; charset=utf-8','Content-Length':Buffer.byteLength(b),'Cache-Control':'no-store','X-Content-Type-Options':'nosniff','Referrer-Policy':'no-referrer'});res.end(b);}
function fail(res,status,error){json(res,status,{error});}
async function body(req){let a=[];let n=0;for await(const c of req){n+=c.length;if(n>MAX_BODY)throw Object.assign(new Error('Request too large'),{status:413});a.push(c);}try{return JSON.parse(Buffer.concat(a).toString('utf8')||'{}')}catch{throw Object.assign(new Error('Invalid JSON'),{status:400})}}
function clean(s,max=500){return String(s??'').trim().slice(0,max)}
const hits=new Map();function rate(req,res){const ip=req.socket.remoteAddress||'unknown';const x=hits.get(ip)||{start:now(),n:0};if(now()-x.start>RATE_WINDOW){x.start=now();x.n=0;}x.n++;hits.set(ip,x);if(x.n>RATE_MAX){fail(res,429,'Too many requests. Try again shortly.');return false;}return true;}
function chatFor(userId,chatId){const c=db.chats.find(c=>c.id===chatId&&c.members.includes(userId));return c;}
function shapeChat(c,userId){const members=c.members.map(uid=>safeUser(db.users.find(u=>u.id===uid))).filter(Boolean);const msgs=db.messages.filter(m=>m.chatId===c.id).slice(-1)[0]||null;const other=members.find(u=>u.id!==userId);return {id:c.id,name:c.type==='group'?c.name:(other?.displayName||'Unknown'),type:c.type,members,lastMessage:msgs?{text:msgs.text,createdAt:msgs.createdAt,senderId:msgs.senderId}:null,createdAt:c.createdAt};}
function sendWs(client,obj){if(!client._wsOpen)return;const payload=Buffer.from(JSON.stringify(obj));let head;if(payload.length<126){head=Buffer.from([0x81,payload.length]);}else if(payload.length<65536){head=Buffer.alloc(4);head[0]=0x81;head[1]=126;head.writeUInt16BE(payload.length,2);}else{head=Buffer.alloc(10);head[0]=0x81;head[1]=127;head.writeBigUInt64BE(BigInt(payload.length),2);}client.write(Buffer.concat([head,payload]));}
const sockets=new Set();function broadcastChat(chatId,obj){for(const s of sockets)if(s.userId&&chatFor(s.userId,chatId))sendWs(s,obj);}
const server=http.createServer(async(req,res)=>{
 if(!rate(req,res))return;
 const url=new URL(req.url,'http://localhost');
 if(url.pathname.startsWith('/api/')){
  const origin=req.headers.origin;
  if(origin && ALLOWED_ORIGINS.includes(origin)){res.setHeader('Access-Control-Allow-Origin',origin);res.setHeader('Vary','Origin');res.setHeader('Access-Control-Allow-Headers','Content-Type, Authorization');res.setHeader('Access-Control-Allow-Methods','GET, POST, DELETE, OPTIONS');}
  if(req.method==='OPTIONS'){res.writeHead(204);return res.end();}
  try{
   if(req.method==='GET'&&url.pathname==='/api/health')return json(res,200,{ok:true,service:'NEXA Messenger',mode:'self-hosted',time:new Date().toISOString()});
   if(req.method==='POST'&&url.pathname==='/api/register'){
    const b=await body(req),username=clean(b.username,24).toLowerCase(),displayName=clean(b.displayName||b.username,40),password=String(b.password||'');
    if(!/^[a-z0-9_]{3,24}$/.test(username))return fail(res,400,'Username must be 3–24 characters: a-z, 0-9, underscore.');
    if(displayName.length<1)return fail(res,400,'Display name is required.');if(password.length<10||password.length>128)return fail(res,400,'Password must be 10–128 characters.');
    if(db.users.some(u=>u.username===username))return fail(res,409,'That username is already taken.');
    const hp=hashPassword(password),u={id:id(),username,displayName,salt:hp.salt,passwordHash:hp.hash,createdAt:new Date().toISOString()};db.users.push(u);const token=crypto.randomBytes(32).toString('base64url');db.sessions.push({token,userId:u.id,expiresAt:now()+30*24*60*60*1000});save();return json(res,201,{token,user:safeUser(u)});
   }
   if(req.method==='POST'&&url.pathname==='/api/login'){
    const b=await body(req),username=clean(b.username,24).toLowerCase(),password=String(b.password||''),u=db.users.find(u=>u.username===username);
    if(!u||password.length>128||!verifyPassword(password,u))return fail(res,401,'Incorrect username or password.');
    const token=crypto.randomBytes(32).toString('base64url');db.sessions=db.sessions.filter(s=>s.expiresAt>now());db.sessions.push({token,userId:u.id,expiresAt:now()+30*24*60*60*1000});save();return json(res,200,{token,user:safeUser(u)});
   }
   const token=tokenFrom(req),me=tokenUser(token);
   if(req.method==='POST'&&url.pathname==='/api/logout'){db.sessions=db.sessions.filter(s=>s.token!==token);save();return json(res,200,{ok:true});}
   if(!me)return fail(res,401,'Sign in to continue.');
   if(req.method==='GET'&&url.pathname==='/api/me')return json(res,200,{user:safeUser(me)});
   if(req.method==='GET'&&url.pathname==='/api/users'){
    const q=clean(url.searchParams.get('q'),50).toLowerCase();const users=db.users.filter(u=>u.id!==me.id&&(!q||u.username.includes(q)||u.displayName.toLowerCase().includes(q))).slice(0,30).map(safeUser);return json(res,200,{users});
   }
   if(req.method==='GET'&&url.pathname==='/api/chats')return json(res,200,{chats:db.chats.filter(c=>c.members.includes(me.id)).map(c=>shapeChat(c,me.id)).sort((a,b)=>new Date(b.lastMessage?.createdAt||b.createdAt)-new Date(a.lastMessage?.createdAt||a.createdAt))});
   if(req.method==='POST'&&url.pathname==='/api/chats'){
    const b=await body(req),type=b.type==='group'?'group':'direct',name=clean(b.name,60),memberNames=Array.isArray(b.usernames)?b.usernames.map(x=>clean(x,24).toLowerCase()).filter(Boolean):[];
    let members=[me.id,...new Set(memberNames.map(n=>db.users.find(u=>u.username===n)?.id).filter(Boolean))];
    if(type==='direct'){if(members.length!==2)return fail(res,400,'Enter the username of one existing user.');const found=db.chats.find(c=>c.type==='direct'&&c.members.length===2&&c.members.every(x=>members.includes(x)));if(found)return json(res,200,{chat:shapeChat(found,me.id)});}
    else{if(name.length<2)return fail(res,400,'Group name must be at least 2 characters.');if(memberNames.length<1||members.length<2)return fail(res,400,'Add at least one existing member by username.');}
    const c={id:id(),type,name:type==='group'?name:null,members:[...new Set(members)],createdAt:new Date().toISOString()};db.chats.push(c);save();for(const uid of c.members)for(const s of sockets)if(s.userId===uid)sendWs(s,{type:'chat_created',chat:shapeChat(c,uid)});return json(res,201,{chat:shapeChat(c,me.id)});
   }
   const cm=url.pathname.match(/^\/api\/chats\/([\w-]+)\/messages$/);
   if(cm&&req.method==='GET'){const c=chatFor(me.id,cm[1]);if(!c)return fail(res,404,'Conversation not found.');const before=url.searchParams.get('before');let msgs=db.messages.filter(m=>m.chatId===c.id);if(before)msgs=msgs.filter(m=>m.createdAt<before);return json(res,200,{messages:msgs.slice(-100).map(m=>({...m,sender:safeUser(db.users.find(u=>u.id===m.senderId))}))});}
   if(cm&&req.method==='POST'){const c=chatFor(me.id,cm[1]);if(!c)return fail(res,404,'Conversation not found.');const b=await body(req),text=clean(b.text,2000);if(!text)return fail(res,400,'Message cannot be empty.');const m={id:id(),chatId:c.id,senderId:me.id,text,createdAt:new Date().toISOString()};db.messages.push(m);save();const out={type:'message',message:{...m,sender:safeUser(me)}};broadcastChat(c.id,out);return json(res,201,{message:out.message});}
   return fail(res,404,'API route not found.');
  }catch(e){console.error(e);return fail(res,e.status||500,e.status?e.message:'Internal server error.');}
 }
 let p=url.pathname==='/'?'/index.html':decodeURIComponent(url.pathname);const file=path.resolve(PUB,'.'+p);if(!file.startsWith(PUB+path.sep)){res.writeHead(403);return res.end('Forbidden');}
 fs.readFile(file,(err,data)=>{if(err){res.writeHead(404,{'Content-Type':'text/plain'});return res.end('Not found');}const ext=path.extname(file);const types={'.html':'text/html; charset=utf-8','.css':'text/css; charset=utf-8','.js':'text/javascript; charset=utf-8','.svg':'image/svg+xml'};res.writeHead(200,{'Content-Type':types[ext]||'application/octet-stream','X-Content-Type-Options':'nosniff','Referrer-Policy':'no-referrer','Cache-Control':ext==='.html'?'no-cache':'public, max-age=3600'});res.end(data);});
});
// Minimal RFC 6455 WebSocket server. Text frames only; clients must authenticate with a valid bearer session token in the query.
server.on('upgrade',(req,socket)=>{const url=new URL(req.url,'http://localhost');if(url.pathname!=='/ws'||!req.headers['sec-websocket-key']||req.headers['upgrade']?.toLowerCase()!=='websocket'){socket.destroy();return;}const user=tokenUser(url.searchParams.get('token')||'');if(!user){socket.write('HTTP/1.1 401 Unauthorized\r\nConnection: close\r\n\r\n');socket.destroy();return;}const accept=crypto.createHash('sha1').update(req.headers['sec-websocket-key']+'258EAFA5-E914-47DA-95CA-C5AB0DC85B11').digest('base64');socket.write('HTTP/1.1 101 Switching Protocols\r\nUpgrade: websocket\r\nConnection: Upgrade\r\nSec-WebSocket-Accept: '+accept+'\r\n\r\n');socket.userId=user.id;socket._wsOpen=true;sockets.add(socket);socket.on('data',buf=>{try{let off=0;while(off+2<=buf.length){const a=buf[off++],b=buf[off++];let len=b&127;if(len===126){if(off+2>buf.length)break;len=buf.readUInt16BE(off);off+=2;}else if(len===127){if(off+8>buf.length)break;len=Number(buf.readBigUInt64BE(off));off+=8;}const masked=!!(b&128);if(len>65536){socket.destroy();return;}let mask;if(masked){if(off+4>buf.length)break;mask=buf.subarray(off,off+4);off+=4;}if(off+len>buf.length)break;let payload=Buffer.from(buf.subarray(off,off+len));off+=len;if(masked)for(let i=0;i<payload.length;i++)payload[i]^=mask[i%4];if((a&15)===8){socket.end();return;}if((a&15)===9){const pong=Buffer.concat([Buffer.from([0x8a,payload.length]),payload]);socket.write(pong);}}}catch{socket.destroy();}});socket.on('close',()=>{sockets.delete(socket);socket._wsOpen=false;});socket.on('error',()=>{sockets.delete(socket);socket._wsOpen=false;});});
server.listen(PORT,HOST,()=>console.log(`NEXA Messenger running at http://${HOST}:${PORT}`));
