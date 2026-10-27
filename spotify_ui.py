"""Small Spotify listening controls, separate from recommendation evidence."""


def spotify_page() -> str:
    return r'''<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Spotify | Crate Digger</title>
<style>
:root{color-scheme:light;--ink:#171d1d;--muted:#5c6663;--paper:#dfe4e1;--surface:#f0f2ed;--line:#a3ada6;--dark:#17343a}
*{box-sizing:border-box}body{margin:0;background:var(--paper);color:var(--ink);font:16px/1.5 system-ui,sans-serif}main{max-width:860px;margin:auto;padding:28px 20px 70px}a{color:var(--dark)}h1,h2{font-family:Georgia,serif;font-weight:500}h1{font-size:42px;margin-bottom:12px}h2{font-size:25px;margin:0 0 15px}.muted{color:var(--muted)}section{padding:22px;background:var(--surface);border:1px solid var(--line);margin:20px 0}button,input,select{font:inherit}button,.button{display:inline-block;border:1px solid var(--dark);padding:8px 13px;background:var(--dark);color:white;border-radius:5px;cursor:pointer;text-decoration:none}button:disabled{opacity:.45;cursor:default}input,select{max-width:100%;padding:8px;border:1px solid var(--line);background:white;color:var(--ink)}input[type=search]{flex:1;min-width:150px}.row{display:flex;flex-wrap:wrap;align-items:center;gap:10px}.row+.row{margin-top:12px}label{display:block}#message{padding:12px 0;min-height:48px;white-space:pre-wrap}#results{list-style:none;padding:0}#results li{border-top:1px solid var(--line);padding:13px 0;display:flex;align-items:center;gap:12px}#results .info{flex:1;min-width:0}#results small{display:block;color:var(--muted)}#results button{font-size:13px;padding:6px 9px}.selection{font-weight:600}button:focus-visible,a:focus-visible,input:focus-visible,select:focus-visible{outline:3px solid #9e332f;outline-offset:3px}[hidden]{display:none!important}
</style></head><body><main>
<a href="/listen">← Back to recommendations</a>
<h1>Listen with Spotify</h1>
<p class="muted">Find a recommended album or track, choose what to send, and listen on your Spotify device.</p>
<section aria-labelledby="account-title"><h2 id="account-title">Your account</h2>
<p id="account">Checking connection…</p>
<div class="row"><a class="button" id="connect" href="/spotify/connect" hidden>Connect Spotify</a><button id="disconnect" hidden>Disconnect</button></div>
<p class="muted">Connection lasts up to eight hours and ends when the server restarts. Disconnect removes this session; revoke app access in Spotify to remove its permissions.</p>
</section>
<div id="message" role="status" aria-live="polite"></div>
<div id="controls" hidden>
<section aria-labelledby="search-title"><h2 id="search-title">Choose music</h2>
<form id="search-form" class="row"><input id="query" type="search" maxlength="200" required aria-label="Artist, album, or track" placeholder="Artist, album, or track"><select id="kind" aria-label="Search type"><option value="album">Albums</option><option value="track">Tracks</option></select><button>Search Spotify</button></form>
<p class="muted">These are Spotify search matches for you to select. They do not become recommendation evidence.</p>
<div class="row"><span id="selected" class="selection">0 tracks selected</span><button id="clear">Clear selection</button><button id="select-visible">Select visible tracks</button></div>
<ul id="results"></ul><button id="more-tracks" hidden>More album tracks</button>
</section>
<section aria-labelledby="playlist-title"><h2 id="playlist-title">Send selected tracks</h2>
<div class="row"><label>New private playlist <input id="playlist-name" maxlength="100" value="Crate Digger discoveries"></label><button id="create">Create playlist with selected tracks</button></div>
<div class="row"><button id="load-playlists">Load my private playlists</button><select id="playlists" aria-label="Your private playlists"><option value="">Choose a playlist</option></select><button id="add">Add selected tracks</button><button id="more-playlists" hidden>More playlists</button></div>
<p class="muted">Playlist changes happen only when you press a send button. Up to 100 tracks per action.</p>
<p id="playlist-result"></p>
</section>
<section aria-labelledby="player-title"><h2 id="player-title">Spotify playback</h2>
<p class="muted">Requires Spotify Premium. Open Spotify and start a track to make a device available.</p>
<div class="row"><button id="refresh-player">Refresh devices and playback</button><select id="devices" aria-label="Spotify device"><option value="">Active device</option></select></div>
<p id="now-playing">Playback has not been checked.</p>
<div class="row"><button id="play-selected">Play selected tracks</button><button data-player="play">Resume</button><button data-player="pause">Pause</button><button data-player="previous">Previous</button><button data-player="next">Next</button></div>
</section></div>
</main><script>
const $=id=>document.getElementById(id);
let csrf='',busy=false,visible=[],albumId='',trackOffset=null,playlistOffset=null;
const selected=new Map();
function message(text){$('message').textContent=text;}
async function api(path,body){const response=await fetch('/spotify/'+path,{method:body?'POST':'GET',headers:body?{'Content-Type':'application/json','X-Spotify-CSRF':csrf}:{},body:body?JSON.stringify(body):undefined,cache:'no-store'});let data;try{data=await response.json();}catch{throw new Error('The server returned an unreadable response.');}if(!response.ok){if(data.playlist)showPlaylist(data.playlist);throw new Error(data.message||data.detail||'Spotify request failed.');}return data;}
async function run(work){if(busy)return;busy=true;const buttons=[...document.querySelectorAll('button')];buttons.forEach(b=>b.disabled=true);try{await work();}catch(error){message(error.message);}finally{busy=false;buttons.forEach(b=>b.disabled=false);}}
function updateSelection(){ $('selected').textContent=selected.size+' tracks selected'; }
function choose(item,checked){if(checked&&selected.size>=100&&!selected.has(item.uri)){message('Select up to 100 tracks per action.');return false;}if(checked)selected.set(item.uri,item);else selected.delete(item.uri);updateSelection();return true;}
function trackUris(){if(!selected.size)throw new Error('Choose at least one track first.');return [...selected.keys()];}
function showPlaylist(playlist){const link=document.createElement('a');link.href=playlist.url;link.target='_blank';link.rel='noopener noreferrer';link.textContent='Open '+playlist.name+' in Spotify';$('playlist-result').replaceChildren(link);}
async function send(action,extra={}){const result=await api('action',{action,...extra});if(result.playlist)showPlaylist(result.playlist);message(result.added!==undefined?'Added '+result.added+' tracks to '+result.playlist.name+'.':'Spotify accepted the '+action.replaceAll('_',' ')+' action.');return result;}
function button(label,action){const b=document.createElement('button');b.type='button';b.textContent=label;b.addEventListener('click',()=>run(action));return b;}
function render(items){visible=items;$('results').replaceChildren();for(const item of items){const row=document.createElement('li');if(item.type==='track'){const box=document.createElement('input');box.type='checkbox';box.checked=selected.has(item.uri);box.setAttribute('aria-label','Select '+item.name);box.addEventListener('change',()=>{if(!choose(item,box.checked))box.checked=false;});row.append(box);}const info=document.createElement('div');info.className='info';const link=document.createElement('a');link.href=item.url;link.target='_blank';link.rel='noopener noreferrer';link.textContent=item.name;const small=document.createElement('small');small.textContent=[item.artists,item.album].filter(Boolean).join(' · ');info.append(link,small);row.append(info);if(item.type==='album'){row.append(button('Choose tracks',()=>loadAlbum(item.id,0)),button('Play album',()=>send('play',{context_uri:item.uri,device_id:$('devices').value})));}else{row.append(button('Queue',()=>send('queue',{uris:[item.uri],device_id:$('devices').value})));}$('results').append(row);}if(!items.length)message('No Spotify matches found. Try a different artist or title.');}
async function loadAlbum(id,offset){const data=await api('albums/'+id+'/tracks?offset='+offset);albumId=id;trackOffset=data.next_offset;render(data.items);$('more-tracks').hidden=trackOffset===null;message('Choose tracks from this album.');}
async function loadPlaylists(offset){const data=await api('playlists?offset='+offset);if(offset===0)$('playlists').replaceChildren(new Option('Choose a playlist',''));for(const item of data.items)$('playlists').add(new Option(item.name,item.id));playlistOffset=data.next_offset;$('more-playlists').hidden=playlistOffset===null;message('Loaded private playlists that you own.');}
async function refreshPlayer(){const data=await api('player');$('devices').replaceChildren(new Option('Active device',''));for(const device of data.devices){const option=new Option(device.name+(device.is_active?' (active)':''),device.id);$('devices').add(option);}$('now-playing').textContent=data.item?(data.is_playing?'Playing: ':'Paused: ')+data.item.name+' · '+data.item.artists:'No active track. Open Spotify and start playback.';}
$('search-form').addEventListener('submit',event=>{event.preventDefault();run(async()=>{const data=await api('search?'+new URLSearchParams({q:$('query').value,kind:$('kind').value}));$('more-tracks').hidden=true;render(data.items);if(data.items.length)message('Choose a match to listen or send tracks.');});});
$('more-tracks').onclick=()=>run(()=>loadAlbum(albumId,trackOffset));
$('clear').onclick=()=>{selected.clear();updateSelection();render(visible);};
$('select-visible').onclick=()=>{for(const item of visible)if(item.type==='track'&&!choose(item,true))break;render(visible);};
$('create').onclick=()=>run(()=>send('create_playlist',{name:$('playlist-name').value,uris:trackUris()}));
$('add').onclick=()=>run(()=>send('add_to_playlist',{playlist_id:$('playlists').value,uris:trackUris()}));
$('load-playlists').onclick=()=>run(()=>loadPlaylists(0));
$('more-playlists').onclick=()=>run(()=>loadPlaylists(playlistOffset));
$('refresh-player').onclick=()=>run(refreshPlayer);
$('play-selected').onclick=()=>run(()=>send('play',{uris:trackUris(),device_id:$('devices').value}));
document.querySelectorAll('[data-player]').forEach(b=>b.onclick=()=>run(()=>send(b.dataset.player,{device_id:$('devices').value})));
$('disconnect').onclick=()=>run(async()=>{await api('disconnect',{});location.assign('/spotify');});
async function init(){const data=await api('status');$('controls').hidden=!data.connected;$('connect').hidden=!data.configured;$('disconnect').hidden=!data.connected;csrf=data.csrf||'';$('account').textContent=data.connected?'Connected as '+data.account.name:data.configured?'Connect your Spotify account to choose music and control listening.':'Spotify needs server setup: add SPOTIFY_CLIENT_ID and register the callback URL. See the project README.';$('connect').textContent=data.connected?'Reconnect Spotify':'Connect Spotify';const params=new URLSearchParams(location.search);if(params.get('connection')==='denied')message('Spotify access was declined. You can connect again when ready.');if(data.connected&&params.get('connection')==='ok')message('Spotify connected. Search for music or refresh playback.');const query=params.get('q');if(query)$('query').value=query.slice(0,200);if(params.get('kind')==='track')$('kind').value='track';history.replaceState(null,'','/spotify');}
run(init);
</script></body></html>'''
