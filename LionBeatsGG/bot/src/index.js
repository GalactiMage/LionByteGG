import 'dotenv/config';
import { Client, GatewayIntentBits, REST, Routes, SlashCommandBuilder, EmbedBuilder, ActionRowBuilder, ButtonBuilder, ButtonStyle, AttachmentBuilder, ActivityType, ModalBuilder, TextInputBuilder, TextInputStyle } from 'discord.js';
import { createRequire } from 'node:module';
import fs from 'fs';
import path from 'path';
import http from 'http';
import { fileURLToPath } from 'url';
const require = createRequire(import.meta.url);

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);
const MUSIC_PANELS_FILE = path.join(__dirname, '..', 'data', 'music-panels.json');
const PLAY_HISTORY_FILE = path.join(__dirname, '..', 'data', 'play-history.json');
const BOT_SETTINGS_FILE = path.join(__dirname, '..', 'data', 'bot-settings.json');
const STATS_FILE = path.join(__dirname, '..', 'data', 'music-stats.json');

const { LavalinkManager } = require('lavalink-client');

const client = new Client({
    intents: [
        GatewayIntentBits.Guilds,
        GatewayIntentBits.GuildVoiceStates,
        GatewayIntentBits.GuildMessages,
        GatewayIntentBits.MessageContent
    ]
});

const PREFIX = '!';

// Music control panel storage
const musicPanels = new Map(); // guildId -> { channelId, messageId }
const cooldowns = new Map(); // userId -> { commandName -> timestamp }
const COOLDOWN_TIME = 5000; // 5 seconds
const inactivityTimers = new Map(); // guildId -> timeout
const INACTIVITY_TIMEOUT = 20 * 60 * 1000; // 20 minutes
const bassBoostEnabled = new Map(); // guildId -> boolean
const activeQuizzes = new Map(); // guildId -> quiz game state

// Music Quiz - Load songs from external JSON file
const QUIZ_SONGS_FILE = path.join(__dirname, '..', 'data', 'quiz-songs.json');

function loadQuizSongs() {
    try {
        if (fs.existsSync(QUIZ_SONGS_FILE)) {
            const data = fs.readFileSync(QUIZ_SONGS_FILE, 'utf8');
            return JSON.parse(data);
        }
    } catch (error) {
        console.error('Error loading quiz songs:', error);
    }
    return { pop: [], anime: [] };
}

// Function to get quiz songs for a genre
async function fetchQuizSongs(player, genre, maxSongs = 50) {
    const quizSongs = loadQuizSongs();
    const songList = quizSongs[genre] || [];
    
    if (songList.length === 0) {
        console.log(`Quiz: No songs found for genre "${genre}"`);
        return [];
    }
    
    // Shuffle the song list
    const shuffled = [...songList].sort(() => Math.random() - 0.5);
    const selected = shuffled.slice(0, Math.min(maxSongs * 2, shuffled.length)); // Get more to account for duplicates
    
    // Search and prepare each song
    const preparedSongs = [];
    const usedTrackUris = new Set(); // Track URIs to prevent duplicates
    const usedTitles = new Set(); // Track titles to prevent same song from different sources
    
    for (const song of selected) {
        try {
            let result;
            let foundTrack = null;
            
            // For anime songs, search YouTube (more reliable for anime music)
            if (song.anime) {
                // Try YouTube with anime name + "OP ED" keywords for best match
                result = await player.search({ query: `ytsearch:${song.title} ${song.artist} ${song.anime} OP ED anime` }, client.user);
                if (result && result.tracks && result.tracks.length > 0) {
                    foundTrack = result.tracks[0];
                }
                
                // If that fails, try just with anime name
                if (!foundTrack) {
                    result = await player.search({ query: `ytsearch:${song.title} ${song.anime} anime opening` }, client.user);
                    if (result && result.tracks && result.tracks.length > 0) {
                        foundTrack = result.tracks[0];
                    }
                }
                
                // Try YouTube Music as backup
                if (!foundTrack) {
                    result = await player.search({ query: `ytmsearch:${song.title} ${song.artist} anime` }, client.user);
                    if (result && result.tracks && result.tracks.length > 0) {
                        foundTrack = result.tracks[0];
                    }
                }
            } else {
                // For non-anime songs (pop, rock, etc.), use Spotify first
                result = await player.search({ query: `spsearch:${song.title} ${song.artist}` }, client.user);
                
                if (result && result.tracks && result.tracks.length > 0) {
                    foundTrack = result.tracks[0];
                }
                
                // If Spotify fails, try YouTube Music
                if (!foundTrack) {
                    result = await player.search({ query: `ytmsearch:${song.title} ${song.artist}` }, client.user);
                    if (result && result.tracks && result.tracks.length > 0) {
                        foundTrack = result.tracks[0];
                    }
                }
                
                // If YouTube Music fails, try regular YouTube
                if (!foundTrack) {
                    result = await player.search({ query: `ytsearch:${song.title} ${song.artist}` }, client.user);
                    if (result && result.tracks && result.tracks.length > 0) {
                        foundTrack = result.tracks[0];
                    }
                }
            }
            
            if (!foundTrack) {
                console.log(`Quiz: Could not find "${song.title}" by ${song.artist}`);
                continue;
            }
            
            if (foundTrack) {
                // Check for duplicates by URI and title
                const trackUri = foundTrack.info.uri || foundTrack.info.identifier;
                const titleKey = song.title.toLowerCase().trim();
                
                if (usedTrackUris.has(trackUri) || usedTitles.has(titleKey)) {
                    console.log(`Quiz: Skipping duplicate "${song.title}" (already loaded)`);
                    continue;
                }
                
                usedTrackUris.add(trackUri);
                usedTitles.add(titleKey);
                
                // Generate answers
                const answers = [
                    song.title.toLowerCase(),
                    song.artist.toLowerCase()
                ];
                
                // Add anime name as answer for anime songs
                if (song.anime) {
                    answers.push(song.anime.toLowerCase());
                }
                
                // Add partial title matches
                const titleWords = song.title.toLowerCase().split(' ');
                if (titleWords.length > 1) {
                    answers.push(titleWords[0]); // First word
                }
                
                preparedSongs.push({
                    track: foundTrack,
                    title: song.title,
                    artist: song.artist,
                    anime: song.anime || null,
                    answers: [...new Set(answers)].filter(a => a.length > 2)
                });
                
                console.log(`Quiz: Loaded "${song.title}" by ${song.artist} -> ${foundTrack.info.title}`);
            } else {
                console.log(`Quiz: Could not find "${song.title}" by ${song.artist}`);
            }
            
            // Stop if we have enough
            if (preparedSongs.length >= maxSongs) break;
            
        } catch (error) {
            console.error(`Quiz: Error searching for "${song.search}":`, error.message);
        }
    }
    
    return preparedSongs;
}

// Load music panels from file
function loadMusicPanels() {
    try {
        if (fs.existsSync(MUSIC_PANELS_FILE)) {
            const data = fs.readFileSync(MUSIC_PANELS_FILE, 'utf8');
            const panels = JSON.parse(data);
            Object.entries(panels).forEach(([guildId, panelData]) => {
                musicPanels.set(guildId, panelData);
            });
            console.log(`📋 Loaded ${musicPanels.size} music panel(s)`);
        }
    } catch (error) {
        console.error('Error loading music panels:', error);
    }
}

// Save music panels to file
function saveMusicPanels() {
    try {
        const dataDir = path.join(__dirname, '..', 'data');
        if (!fs.existsSync(dataDir)) {
            fs.mkdirSync(dataDir, { recursive: true });
        }
        const panels = Object.fromEntries(musicPanels);
        fs.writeFileSync(MUSIC_PANELS_FILE, JSON.stringify(panels, null, 2));
    } catch (error) {
        console.error('Error saving music panels:', error);
    }
}

// ============ Play History & Statistics ============
const MAX_HISTORY_ENTRIES = 1000; // Keep last 1000 plays

function loadPlayHistory() {
    try {
        if (fs.existsSync(PLAY_HISTORY_FILE)) {
            return JSON.parse(fs.readFileSync(PLAY_HISTORY_FILE, 'utf8'));
        }
    } catch (error) {
        console.error('Error loading play history:', error);
    }
    return [];
}

function savePlayHistory(history) {
    try {
        const dataDir = path.join(__dirname, '..', 'data');
        if (!fs.existsSync(dataDir)) {
            fs.mkdirSync(dataDir, { recursive: true });
        }
        // Keep only last MAX_HISTORY_ENTRIES
        const trimmed = history.slice(-MAX_HISTORY_ENTRIES);
        fs.writeFileSync(PLAY_HISTORY_FILE, JSON.stringify(trimmed, null, 2));
    } catch (error) {
        console.error('Error saving play history:', error);
    }
}

function addToPlayHistory(track, guildId, guildName) {
    const history = loadPlayHistory();
    history.push({
        title: track.info.title,
        author: track.info.author,
        uri: track.info.uri,
        duration: track.info.duration,
        artworkUrl: track.info.artworkUrl || track.info.thumbnail || null,
        requesterId: track.requester?.id || null,
        requesterName: track.requester?.username || track.requester?.tag || 'Unknown',
        guildId: guildId,
        guildName: guildName,
        playedAt: new Date().toISOString()
    });
    savePlayHistory(history);
    updateStats(track, guildId);
}

function clearPlayHistory() {
    savePlayHistory([]);
    console.log('🗑️ Play history cleared');
}

// ============ Music Statistics ============
function loadStats() {
    try {
        if (fs.existsSync(STATS_FILE)) {
            return JSON.parse(fs.readFileSync(STATS_FILE, 'utf8'));
        }
    } catch (error) {
        console.error('Error loading stats:', error);
    }
    return {
        totalPlays: 0,
        topSongs: {},
        topRequesters: {},
        hourlyActivity: {},
        dailyActivity: {}
    };
}

function saveStats(stats) {
    try {
        const dataDir = path.join(__dirname, '..', 'data');
        if (!fs.existsSync(dataDir)) {
            fs.mkdirSync(dataDir, { recursive: true });
        }
        fs.writeFileSync(STATS_FILE, JSON.stringify(stats, null, 2));
    } catch (error) {
        console.error('Error saving stats:', error);
    }
}

function updateStats(track, guildId) {
    const stats = loadStats();
    stats.totalPlays = (stats.totalPlays || 0) + 1;
    
    // Track top songs
    const songKey = `${track.info.title}|||${track.info.author}`;
    stats.topSongs[songKey] = (stats.topSongs[songKey] || 0) + 1;
    
    // Track top requesters
    if (track.requester?.id) {
        const requesterKey = `${track.requester.id}|||${track.requester.username || track.requester.tag || 'Unknown'}`;
        stats.topRequesters[requesterKey] = (stats.topRequesters[requesterKey] || 0) + 1;
    }
    
    // Track hourly activity
    const hour = new Date().getHours();
    stats.hourlyActivity[hour] = (stats.hourlyActivity[hour] || 0) + 1;
    
    // Track daily activity
    const today = new Date().toISOString().split('T')[0];
    stats.dailyActivity[today] = (stats.dailyActivity[today] || 0) + 1;
    
    // Trim old daily activity (keep last 90 days)
    const dates = Object.keys(stats.dailyActivity).sort();
    if (dates.length > 90) {
        dates.slice(0, dates.length - 90).forEach(d => delete stats.dailyActivity[d]);
    }
    
    saveStats(stats);
}

function clearStats() {
    saveStats({
        totalPlays: 0,
        topSongs: {},
        topRequesters: {},
        hourlyActivity: {},
        dailyActivity: {}
    });
    console.log('🗑️ Statistics cleared');
}

// ============ Bot Settings ============
function loadBotSettings() {
    try {
        if (fs.existsSync(BOT_SETTINGS_FILE)) {
            return JSON.parse(fs.readFileSync(BOT_SETTINGS_FILE, 'utf8'));
        }
    } catch (error) {
        console.error('Error loading bot settings:', error);
    }
    return {
        activityText: 'LionBeatsGG 🎵',
        activityType: 'listening',
        defaultVolume: 100,
        maxVolume: 150,
        autoDisconnectMinutes: 20,
        djRoleId: null
    };
}

function saveBotSettings(settings) {
    try {
        const dataDir = path.join(__dirname, '..', 'data');
        if (!fs.existsSync(dataDir)) {
            fs.mkdirSync(dataDir, { recursive: true });
        }
        fs.writeFileSync(BOT_SETTINGS_FILE, JSON.stringify(settings, null, 2));
    } catch (error) {
        console.error('Error saving bot settings:', error);
    }
}

// ============ Quiz Songs Management ============
function saveQuizSongs(songs) {
    try {
        const dataDir = path.join(__dirname, '..', 'data');
        if (!fs.existsSync(dataDir)) {
            fs.mkdirSync(dataDir, { recursive: true });
        }
        fs.writeFileSync(QUIZ_SONGS_FILE, JSON.stringify(songs, null, 2));
    } catch (error) {
        console.error('Error saving quiz songs:', error);
    }
}

// --- Lavalink Setup ---
client.lavalink = new LavalinkManager({
    nodes: [
        {
            authorization: 'pnwesports123',
            host: '127.0.0.1',
            port: 2333,
            id: 'main',
            secure: false
        }
    ],
    sendToShard: (guildId, payload) => {
        const guild = client.guilds.cache.get(guildId);
        if (guild) guild.shard.send(payload);
    },
    autoSkip: true
});

// Handle Lavalink errors to prevent crashes
client.lavalink.nodeManager.on('error', (node, error) => {
    console.error(`Lavalink node error on ${node.options.id}:`, error.message || error);
});

client.lavalink.nodeManager.on('connect', (node) => {
    console.log(`✅ Lavalink node ${node.options.id} connected successfully!`);
});

client.lavalink.nodeManager.on('disconnect', (node, reason) => {
    console.warn(`Lavalink node ${node.options.id} disconnected. Reason:`, reason);
});

client.lavalink.nodeManager.on('reconnecting', (node) => {
    console.log(`Lavalink node ${node.options.id} is reconnecting...`);
});

// --- Slash Command Setup ---
const commands = [
    new SlashCommandBuilder()
        .setName('play')
        .setDescription('Play a song in your voice channel')
        .addStringOption(option =>
            option.setName('query')
                .setDescription('Song name or URL')
                .setRequired(true)
        ),
    new SlashCommandBuilder()
        .setName('restart')
        .setDescription('Restart the bot (admin only)'),
    new SlashCommandBuilder()
        .setName('quiz')
        .setDescription('Start a music quiz game!')
        .addStringOption(option =>
            option.setName('genre')
                .setDescription('Choose a genre')
                .setRequired(true)
                .addChoices(
                    { name: '🎤 Pop Hits', value: 'pop' },
                    { name: '🎌 Anime Openings', value: 'anime' },
                    { name: '💕 Romance Anime', value: 'romance' },
                    { name: '🎸 Rock Classics', value: 'rock' },
                    { name: '🎵 R&B / Soul', value: 'rnb' },
                    { name: '🔥 Hip-Hop / Rap', value: 'hiphop' },
                    { name: '🎧 EDM / Dance', value: 'edm' }
                )
        )
        .addIntegerOption(option =>
            option.setName('rounds')
                .setDescription('Number of rounds (1-10)')
                .setRequired(false)
                .setMinValue(1)
                .setMaxValue(10)
        ),
    new SlashCommandBuilder()
        .setName('set-activity')
        .setDescription('Set a custom activity status for the bot (Admin only)')
        .addStringOption(option =>
            option.setName('activity')
                .setDescription('The activity text to display')
                .setRequired(true)
        )
        .addStringOption(option =>
            option.setName('type')
                .setDescription('Activity type')
                .setRequired(false)
                .addChoices(
                    { name: '🎮 Playing', value: 'playing' },
                    { name: '🎵 Listening to', value: 'listening' },
                    { name: '📺 Watching', value: 'watching' },
                    { name: '🏆 Competing in', value: 'competing' }
                )
        ),
    new SlashCommandBuilder()
        .setName('set-default')
        .setDescription('Reset bot activity to default (Admin only)')
].map(cmd => cmd.toJSON());

const rest = new REST({ version: '10' }).setToken(process.env.DISCORD_TOKEN);

client.on('raw', d => client.lavalink.sendRawData(d));

client.once('ready', async () => {
    console.log(`🦁 LionBeatsGG is online as ${client.user.tag}`);
    client.user.setPresence({
        activities: [{ name: 'LionBeatsGG 🎵', type: ActivityType.Listening }],
        status: 'online'
    });

    // Load saved music panels
    loadMusicPanels();

    // Initialize Lavalink
    client.lavalink.init({ ...client.user });

    // Register slash commands
    try {
        const guildId = '728274695673348140';
        await rest.put(Routes.applicationGuildCommands(client.user.id, guildId), { body: commands });
        console.log('✅ Slash commands registered!');
    } catch (error) {
        console.error('Error registering commands:', error);
    }

    // Start HTTP API server for web dashboard integration
    const API_PORT = process.env.API_PORT || 3847;
    const httpServer = http.createServer(async (req, res) => {
        // Set CORS headers
        res.setHeader('Access-Control-Allow-Origin', '*');
        res.setHeader('Access-Control-Allow-Methods', 'GET, POST, PUT, DELETE, OPTIONS');
        res.setHeader('Access-Control-Allow-Headers', 'Content-Type');
        res.setHeader('Content-Type', 'application/json');

        if (req.method === 'OPTIONS') {
            res.writeHead(200);
            res.end();
            return;
        }

        // Helper to parse JSON body
        const parseBody = () => new Promise((resolve) => {
            let body = '';
            req.on('data', chunk => body += chunk);
            req.on('end', () => {
                try { resolve(JSON.parse(body)); } 
                catch { resolve({}); }
            });
        });

        // Parse URL
        const url = new URL(req.url, `http://localhost:${API_PORT}`);
        const pathname = url.pathname;

        // ============ STATUS ENDPOINTS ============
        if (pathname === '/api/status' && req.method === 'GET') {
            const players = [];
            client.lavalink.players.forEach((player, guildId) => {
                const guild = client.guilds.cache.get(guildId);
                const track = player.queue.current;
                const voiceChannel = guild?.channels.cache.get(player.voiceChannelId);
                
                players.push({
                    guildId: guildId,
                    guildName: guild?.name || 'Unknown',
                    voiceChannel: voiceChannel?.name || null,
                    voiceChannelId: player.voiceChannelId,
                    playing: player.playing,
                    paused: player.paused,
                    position: player.position,
                    volume: player.volume,
                    currentTrack: track ? {
                        title: track.info.title,
                        author: track.info.author,
                        duration: track.info.duration,
                        uri: track.info.uri,
                        artworkUrl: track.info.artworkUrl || track.info.thumbnail || (track.info.sourceName === 'youtube' ? `https://i.ytimg.com/vi/${track.info.identifier}/maxresdefault.jpg` : null),
                        requester: track.requester ? {
                            id: track.requester.id,
                            username: track.requester.username || track.requester.tag
                        } : null
                    } : null,
                    queueLength: player.queue.tracks.length,
                    queue: player.queue.tracks.slice(0, 10).map(t => ({
                        title: t.info.title,
                        author: t.info.author,
                        duration: t.info.duration,
                        uri: t.info.uri
                    }))
                });
            });

            res.writeHead(200);
            res.end(JSON.stringify({
                status: 'online',
                botName: client.user?.tag || 'LionBeatsGG',
                botId: client.user?.id,
                guilds: client.guilds.cache.size,
                activePlayers: players.length,
                players: players,
                uptime: process.uptime()
            }));
        }
        
        // ============ HISTORY ENDPOINTS ============
        else if (pathname === '/api/history' && req.method === 'GET') {
            const limit = parseInt(url.searchParams.get('limit')) || 50;
            const history = loadPlayHistory();
            res.writeHead(200);
            res.end(JSON.stringify({
                total: history.length,
                history: history.slice(-limit).reverse()
            }));
        }
        else if (pathname === '/api/history/clear' && req.method === 'POST') {
            clearPlayHistory();
            res.writeHead(200);
            res.end(JSON.stringify({ success: true, message: 'Play history cleared' }));
        }
        
        // ============ STATISTICS ENDPOINTS ============
        else if (pathname === '/api/stats' && req.method === 'GET') {
            const stats = loadStats();
            
            // Convert top songs to sorted array
            const topSongs = Object.entries(stats.topSongs || {})
                .map(([key, count]) => {
                    const [title, author] = key.split('|||');
                    return { title, author, plays: count };
                })
                .sort((a, b) => b.plays - a.plays)
                .slice(0, 20);
            
            // Convert top requesters to sorted array
            const topRequesters = Object.entries(stats.topRequesters || {})
                .map(([key, count]) => {
                    const [id, name] = key.split('|||');
                    return { id, name, plays: count };
                })
                .sort((a, b) => b.plays - a.plays)
                .slice(0, 20);
            
            res.writeHead(200);
            res.end(JSON.stringify({
                totalPlays: stats.totalPlays || 0,
                topSongs,
                topRequesters,
                hourlyActivity: stats.hourlyActivity || {},
                dailyActivity: stats.dailyActivity || {}
            }));
        }
        else if (pathname === '/api/stats/clear' && req.method === 'POST') {
            clearStats();
            res.writeHead(200);
            res.end(JSON.stringify({ success: true, message: 'Statistics cleared' }));
        }
        
        // ============ QUIZ SONGS ENDPOINTS ============
        else if (pathname === '/api/quiz/songs' && req.method === 'GET') {
            const songs = loadQuizSongs();
            const genre = url.searchParams.get('genre');
            if (genre && songs[genre]) {
                res.writeHead(200);
                res.end(JSON.stringify({ genre, songs: songs[genre], total: songs[genre].length }));
            } else {
                // Return all genres with counts
                const genres = Object.entries(songs).map(([name, list]) => ({
                    genre: name,
                    count: list.length
                }));
                res.writeHead(200);
                res.end(JSON.stringify({ genres, allSongs: songs }));
            }
        }
        else if (pathname === '/api/quiz/songs' && req.method === 'POST') {
            const body = await parseBody();
            const { genre, title, artist, search, anime } = body;
            
            if (!genre || !title || !artist) {
                res.writeHead(400);
                res.end(JSON.stringify({ error: 'Missing required fields: genre, title, artist' }));
                return;
            }
            
            const songs = loadQuizSongs();
            if (!songs[genre]) songs[genre] = [];
            
            const newSong = {
                search: search || `${title} ${artist}`,
                title,
                artist
            };
            if (anime) newSong.anime = anime;
            
            songs[genre].push(newSong);
            saveQuizSongs(songs);
            
            res.writeHead(200);
            res.end(JSON.stringify({ success: true, message: `Added "${title}" to ${genre}`, song: newSong }));
        }
        else if (pathname === '/api/quiz/songs' && req.method === 'DELETE') {
            const body = await parseBody();
            const { genre, index } = body;
            
            if (!genre || index === undefined) {
                res.writeHead(400);
                res.end(JSON.stringify({ error: 'Missing required fields: genre, index' }));
                return;
            }
            
            const songs = loadQuizSongs();
            if (!songs[genre] || !songs[genre][index]) {
                res.writeHead(404);
                res.end(JSON.stringify({ error: 'Song not found' }));
                return;
            }
            
            const removed = songs[genre].splice(index, 1)[0];
            saveQuizSongs(songs);
            
            res.writeHead(200);
            res.end(JSON.stringify({ success: true, message: `Removed "${removed.title}"`, removed }));
        }
        
        // ============ MUSIC PANELS ENDPOINTS ============
        else if (pathname === '/api/panels' && req.method === 'GET') {
            const panels = [];
            musicPanels.forEach((panel, guildId) => {
                const guild = client.guilds.cache.get(guildId);
                const channel = guild?.channels.cache.get(panel.channelId);
                panels.push({
                    guildId,
                    guildName: guild?.name || 'Unknown',
                    channelId: panel.channelId,
                    channelName: channel?.name || 'Unknown',
                    messageId: panel.messageId
                });
            });
            res.writeHead(200);
            res.end(JSON.stringify({ panels, total: panels.length }));
        }
        else if (pathname.startsWith('/api/panels/') && req.method === 'DELETE') {
            const guildId = pathname.split('/')[3];
            if (musicPanels.has(guildId)) {
                musicPanels.delete(guildId);
                saveMusicPanels();
                res.writeHead(200);
                res.end(JSON.stringify({ success: true, message: 'Panel removed' }));
            } else {
                res.writeHead(404);
                res.end(JSON.stringify({ error: 'Panel not found' }));
            }
        }
        
        // ============ BOT SETTINGS ENDPOINTS ============
        else if (pathname === '/api/settings' && req.method === 'GET') {
            const settings = loadBotSettings();
            res.writeHead(200);
            res.end(JSON.stringify(settings));
        }
        else if (pathname === '/api/settings' && req.method === 'PUT') {
            const body = await parseBody();
            const settings = loadBotSettings();
            
            // Update only provided fields
            if (body.activityText !== undefined) settings.activityText = body.activityText;
            if (body.activityType !== undefined) settings.activityType = body.activityType;
            if (body.defaultVolume !== undefined) settings.defaultVolume = Math.max(0, Math.min(200, body.defaultVolume));
            if (body.maxVolume !== undefined) settings.maxVolume = Math.max(0, Math.min(200, body.maxVolume));
            if (body.autoDisconnectMinutes !== undefined) settings.autoDisconnectMinutes = Math.max(1, body.autoDisconnectMinutes);
            if (body.djRoleId !== undefined) settings.djRoleId = body.djRoleId;
            
            saveBotSettings(settings);
            
            // Apply activity change immediately
            if (body.activityText !== undefined || body.activityType !== undefined) {
                const typeMap = {
                    'playing': ActivityType.Playing,
                    'listening': ActivityType.Listening,
                    'watching': ActivityType.Watching,
                    'competing': ActivityType.Competing
                };
                client.user.setPresence({
                    activities: [{ 
                        name: settings.activityText, 
                        type: typeMap[settings.activityType] || ActivityType.Listening 
                    }],
                    status: 'online'
                });
            }
            
            res.writeHead(200);
            res.end(JSON.stringify({ success: true, settings }));
        }
        
        // ============ PLAYER CONTROL ENDPOINTS ============
        else if (pathname.startsWith('/api/player/') && req.method === 'POST') {
            const parts = pathname.split('/');
            const guildId = parts[3];
            const action = parts[4];
            
            const player = client.lavalink.players.get(guildId);
            if (!player) {
                res.writeHead(404);
                res.end(JSON.stringify({ error: 'No active player in this server' }));
                return;
            }
            
            try {
                switch (action) {
                    case 'pause':
                        await player.pause();
                        res.writeHead(200);
                        res.end(JSON.stringify({ success: true, paused: true }));
                        break;
                    case 'resume':
                        await player.resume();
                        res.writeHead(200);
                        res.end(JSON.stringify({ success: true, paused: false }));
                        break;
                    case 'skip':
                        await player.skip();
                        res.writeHead(200);
                        res.end(JSON.stringify({ success: true, message: 'Skipped to next track' }));
                        break;
                    case 'stop':
                        // Clear the queue by setting tracks to empty array
                        player.queue.tracks = [];
                        await player.stopTrack();
                        res.writeHead(200);
                        res.end(JSON.stringify({ success: true, message: 'Stopped playback' }));
                        break;
                    case 'volume':
                        const body = await parseBody();
                        const volume = Math.max(0, Math.min(200, body.volume || 100));
                        await player.setVolume(volume);
                        res.writeHead(200);
                        res.end(JSON.stringify({ success: true, volume }));
                        break;
                    case 'shuffle':
                        // Fisher-Yates shuffle algorithm
                        const tracks = player.queue.tracks;
                        for (let i = tracks.length - 1; i > 0; i--) {
                            const j = Math.floor(Math.random() * (i + 1));
                            [tracks[i], tracks[j]] = [tracks[j], tracks[i]];
                        }
                        res.writeHead(200);
                        res.end(JSON.stringify({ success: true, message: 'Queue shuffled' }));
                        break;
                    case 'clear':
                        player.queue.tracks = [];
                        res.writeHead(200);
                        res.end(JSON.stringify({ success: true, message: 'Queue cleared' }));
                        break;
                    default:
                        res.writeHead(400);
                        res.end(JSON.stringify({ error: 'Unknown action' }));
                }
                
                // Update panel after control action
                setTimeout(() => updateMusicPanel(guildId), 500);
            } catch (error) {
                res.writeHead(500);
                res.end(JSON.stringify({ error: error.message }));
            }
        }
        
        // ============ COMMANDS REFERENCE ============
        else if (pathname === '/api/commands' && req.method === 'GET') {
            res.writeHead(200);
            res.end(JSON.stringify({
                prefix: PREFIX,
                slashCommands: [
                    { name: '/play', description: 'Play a song in your voice channel', usage: '/play <song name or URL>' },
                    { name: '/quiz', description: 'Start a music quiz game', usage: '/quiz <genre> [rounds]' },
                    { name: '/set-activity', description: 'Set bot activity status (Admin)', usage: '/set-activity <text> [type]' },
                    { name: '/set-default', description: 'Reset bot activity (Admin)', usage: '/set-default' },
                    { name: '/restart', description: 'Restart the bot (Admin)', usage: '/restart' }
                ],
                prefixCommands: [
                    { name: '!play', description: 'Play a song', usage: '!play <song name or URL>' },
                    { name: '!skip', description: 'Skip current song', usage: '!skip' },
                    { name: '!stop', description: 'Stop playback and clear queue', usage: '!stop' },
                    { name: '!queue', description: 'View the queue', usage: '!queue' },
                    { name: '!nowplaying / !np', description: 'Show current song', usage: '!np' }
                ],
                buttonControls: [
                    'Previous', 'Play/Pause', 'Skip', 'Stop', 'Loop',
                    'Shuffle', 'Queue', 'Lyrics', 'Bass Boost', 'Disconnect'
                ]
            }));
        }
        
        // ============ HEALTH CHECK ============
        else if (pathname === '/api/health' && req.method === 'GET') {
            res.writeHead(200);
            res.end(JSON.stringify({ status: 'healthy', timestamp: Date.now() }));
        }
        
        // ============ 404 ============
        else {
            res.writeHead(404);
            res.end(JSON.stringify({ error: 'Not found' }));
        }
    });

    httpServer.listen(API_PORT, () => {
        console.log(`🌐 HTTP API server running on port ${API_PORT}`);
    });

    // Set request timeout to prevent hanging connections
    httpServer.setTimeout(30000);
});

// ========================= CONNECTION RESILIENCE =========================

client.on('shardDisconnect', (event, shardId) => {
    console.warn(`[CONNECTION] WARNING: Shard ${shardId} disconnected (code: ${event.code}). Will auto-reconnect.`);
});

client.on('shardReconnecting', (shardId) => {
    console.log(`[CONNECTION] Shard ${shardId} reconnecting...`);
});

client.on('shardResume', (shardId, replayedEvents) => {
    console.log(`[CONNECTION] Shard ${shardId} resumed. Replayed ${replayedEvents} events.`);
    // Reload music panels after reconnection to ensure they stay in sync
    loadMusicPanels();
});

client.on('shardError', (error, shardId) => {
    console.error(`[CONNECTION] Shard ${shardId} error:`, error);
});

// Catch unhandled rejections to prevent crashes
process.on('unhandledRejection', (error) => {
    console.error('[PROCESS] Unhandled promise rejection:', error);
});

process.on('uncaughtException', (error) => {
    console.error('[PROCESS] Uncaught exception:', error);
});

// Helper function to generate dynamic color from video ID
function getDynamicColor(videoId, isPaused = false) {
    if (isPaused) return '#FEE75C'; // Yellow for paused
    
    // Generate vibrant color based on video ID hash
    let hash = 0;
    for (let i = 0; i < videoId.length; i++) {
        hash = videoId.charCodeAt(i) + ((hash << 5) - hash);
    }
    
    // Create vibrant, saturated colors using HSL then convert to hex
    const hue = Math.abs(hash % 360);
    const saturation = 65 + (Math.abs(hash) % 20); // 65-85%
    const lightness = 50 + (Math.abs(hash >> 8) % 15); // 50-65%
    
    // Convert HSL to RGB
    const s = saturation / 100;
    const l = lightness / 100;
    const c = (1 - Math.abs(2 * l - 1)) * s;
    const x = c * (1 - Math.abs((hue / 60) % 2 - 1));
    const m = l - c / 2;
    
    let r = 0, g = 0, b = 0;
    if (hue >= 0 && hue < 60) {
        r = c; g = x; b = 0;
    } else if (hue >= 60 && hue < 120) {
        r = x; g = c; b = 0;
    } else if (hue >= 120 && hue < 180) {
        r = 0; g = c; b = x;
    } else if (hue >= 180 && hue < 240) {
        r = 0; g = x; b = c;
    } else if (hue >= 240 && hue < 300) {
        r = x; g = 0; b = c;
    } else {
        r = c; g = 0; b = x;
    }
    
    // Convert to 0-255 range and then to hex
    const toHex = (val) => {
        const hex = Math.round((val + m) * 255).toString(16);
        return hex.length === 1 ? '0' + hex : hex;
    };
    
    return `#${toHex(r)}${toHex(g)}${toHex(b)}`;
}

// Helper function to create music control panel embed
function createMusicEmbed(player) {
    const embed = new EmbedBuilder();

    if (!player || !player.queue.current) {
        embed.setAuthor({ 
            name: '🦁 LionBeats Music Player', 
            iconURL: 'https://cdn.discordapp.com/emojis/741605543046807626.png' 
        })
        .setTitle('⚡ Ready to Play')
        .setDescription('> **No music currently playing**\n> Drop a song link or search term to get started!\n\n**Quick Guide:**\n🎵 Paste a YouTube link or search for a song\n🎮 Use the buttons below to control playback\n📋 Queue unlimited tracks\n⏱️ Auto-disconnect after 20 min idle')
        .setColor('#5865F2')
        .setFooter({ 
            text: 'LionBeatsGG Music • Queue is empty', 
            iconURL: 'https://cdn.discordapp.com/emojis/741605543046807626.png' 
        })
        .setImage('https://cdn.discordapp.com/attachments/1316453330695884912/1454834376478031904/banner.jpg?ex=69528798&is=69513618&hm=a166fc11a7b0faaaf9d7769d06f88b7cb9a5f1f4dadff23eb0bf99b7f45cb743&')
        .setTimestamp();
        return embed;
    }

    const track = player.queue.current;
    const position = player.position;
    const duration = track.info.duration;
    
    const formatTime = (ms) => {
        const seconds = Math.floor((ms / 1000) % 60);
        const minutes = Math.floor((ms / (1000 * 60)) % 60);
        const hours = Math.floor(ms / (1000 * 60 * 60));
        
        if (hours > 0) {
            return `${hours}:${minutes.toString().padStart(2, '0')}:${seconds.toString().padStart(2, '0')}`;
        }
        return `${minutes}:${seconds.toString().padStart(2, '0')}`;
    };

    // Create enhanced visual progress bar
    const percentage = (position / duration) * 100;
    const progress = Math.floor((position / duration) * 30);
    const emptyProgress = 30 - progress;
    
    const progressBar = `${'━'.repeat(progress)}🔘${'─'.repeat(emptyProgress)}`;
    const timeDisplay = `${formatTime(position)} ${progressBar} ${formatTime(duration)}`;

    // Status indicators
    const statusIcon = player.paused ? '⏸️' : '▶️';
    const statusText = player.paused ? 'Paused' : 'Playing';
    
    // Get next track info
    const nextTrack = player.queue.tracks[0];
    const upNextText = nextTrack ? `🎵 ${nextTrack.info.title}` : '—';

    // Author/Artist info
    const author = track.info.author || 'Unknown Artist';

    embed.setAuthor({ 
        name: '🦁 LionBeats Music Player', 
        iconURL: 'https://cdn.discordapp.com/emojis/741605543046807626.png' 
    })
    .setTitle(`${track.info.title}`)
    .setURL(track.info.uri || 'https://www.youtube.com')
    .setDescription(`**${author}**\n\n${timeDisplay}`)
    .addFields(
        { 
            name: '▶️ Playback', 
            value: statusText,
            inline: true 
        },
        { 
            name: '📋 Queue', 
            value: `${player.queue.tracks.length} track${player.queue.tracks.length !== 1 ? 's' : ''}`,
            inline: true 
        },
        { 
            name: '⏱️ Duration', 
            value: formatTime(duration),
            inline: true 
        },
        { name: '\u200b', value: '\u200b', inline: false },
        {
            name: '⏭️ Up Next',
            value: upNextText,
            inline: true
        },
        {
            name: '👤 Requested',
            value: `<@${track.requester.id}>`,
            inline: true
        },
        { name: '\u200b', value: '\u200b', inline: true }
    )
    .setImage(
        track.info.artworkUrl ||
        track.info.thumbnail ||
        (track.info.sourceName === 'spotify' && track.info.image) ||
        `https://i.ytimg.com/vi/${track.info.identifier}/maxresdefault.jpg`
    )
    .setColor(getDynamicColor(track.info.identifier, player.paused))
    .setFooter({ 
        text: `LionBeatsGG Music`, 
        iconURL: track.requester.displayAvatarURL?.() || track.requester.avatar || undefined
    })
    .setTimestamp();

    return embed;
}

// Helper function to create control buttons
function createControlButtons(player) {
    // Get loop mode display
    let loopEmoji = '🔁';
    let loopLabel = 'Loop: Off';
    if (player?.repeatMode === 'track') {
        loopEmoji = '🔂';
        loopLabel = 'Loop: Track';
    } else if (player?.repeatMode === 'queue') {
        loopEmoji = '🔁';
        loopLabel = 'Loop: Queue';
    }

    const row1 = new ActionRowBuilder()
        .addComponents(
            new ButtonBuilder()
                .setCustomId('music_previous')
                .setLabel('Previous')
                .setEmoji('⏮️')
                .setStyle(ButtonStyle.Secondary)
                .setDisabled(!player || !player.queue.previous || player.queue.previous.length === 0),
            new ButtonBuilder()
                .setCustomId('music_playpause')
                .setLabel(player?.paused ? 'Resume' : 'Pause')
                .setEmoji(player?.paused ? '▶️' : '⏸️')
                .setStyle(player?.paused ? ButtonStyle.Success : ButtonStyle.Primary)
                .setDisabled(!player || !player.queue.current),
            new ButtonBuilder()
                .setCustomId('music_stop')
                .setLabel('Stop')
                .setEmoji('⏹️')
                .setStyle(ButtonStyle.Danger)
                .setDisabled(!player || !player.queue.current),
            new ButtonBuilder()
                .setCustomId('music_skip')
                .setLabel('Skip')
                .setEmoji('⏭️')
                .setStyle(ButtonStyle.Secondary)
                .setDisabled(!player || !player.queue.current),
            new ButtonBuilder()
                .setCustomId('music_queue')
                .setLabel('Queue')
                .setEmoji('📜')
                .setStyle(ButtonStyle.Secondary)
                .setDisabled(!player || !player.queue.current)
        );
    
    // Check bass boost status
    const isBassBoostOn = bassBoostEnabled.get(player?.guildId) || false;

    const row2 = new ActionRowBuilder()
        .addComponents(
            new ButtonBuilder()
                .setCustomId('music_loop')
                .setLabel(loopLabel)
                .setEmoji(loopEmoji)
                .setStyle(ButtonStyle.Secondary)
                .setDisabled(!player || !player.queue.current),
            new ButtonBuilder()
                .setCustomId('music_clearqueue')
                .setLabel('Clear Queue')
                .setEmoji('🗑️')
                .setStyle(ButtonStyle.Danger)
                .setDisabled(!player || player.queue.tracks.length === 0),
            new ButtonBuilder()
                .setCustomId('music_volume')
                .setLabel(`Volume: ${player?.displayVolume || 100}%`)
                .setEmoji('🔊')
                .setStyle(ButtonStyle.Secondary)
                .setDisabled(!player || !player.queue.current),
            new ButtonBuilder()
                .setCustomId('music_bassboost')
                .setLabel(isBassBoostOn ? 'Bass: ON' : 'Bass: OFF')
                .setEmoji('🎚️')
                .setStyle(isBassBoostOn ? ButtonStyle.Success : ButtonStyle.Secondary)
                .setDisabled(!player || !player.queue.current),
            new ButtonBuilder()
                .setCustomId('music_lyrics')
                .setLabel('Lyrics')
                .setEmoji('📝')
                .setStyle(ButtonStyle.Secondary)
                .setDisabled(!player || !player.queue.current)
        );
    
    return [row1, row2];
}

// Update music panel
async function updateMusicPanel(guildId) {
    const panelData = musicPanels.get(guildId);
    if (!panelData) return;

    try {
        const channel = await client.channels.fetch(panelData.channelId).catch(() => null);
        if (!channel) {
            // Channel no longer exists, remove from storage
            musicPanels.delete(guildId);
            saveMusicPanels();
            return;
        }
        
        const message = await channel.messages.fetch(panelData.messageId).catch(() => null);
        if (!message) {
            // Message no longer exists, remove from storage
            musicPanels.delete(guildId);
            saveMusicPanels();
            return;
        }
        
        const player = client.lavalink.players.get(guildId);

        const embed = createMusicEmbed(player);
        const buttons = createControlButtons(player);

        await message.edit({ embeds: [embed], components: buttons });
    } catch (error) {
        // Only log unexpected errors
        if (error.code !== 10008) {
            console.error('Error updating music panel:', error.message);
        }
    }
}

// Auto-update music panels every 15 seconds to prevent rate limiting
setInterval(async () => {
    for (const [guildId] of musicPanels) {
        // Skip update if quiz is active to hide song info
        const quiz = activeQuizzes.get(guildId);
        if (quiz && quiz.roundActive) continue;
        
        await updateMusicPanel(guildId);
    }
}, 15000); // Update every 15 seconds to prevent rate limiting

// Helper function to clean YouTube URLs
function cleanYouTubeUrl(query) {
    // If it's a YouTube URL with a video ID, extract just the video ID
    const urlMatch = query.match(/(?:youtube\.com\/watch\?v=|youtu\.be\/)([a-zA-Z0-9_-]{11})/);
    if (urlMatch) {
        return `https://www.youtube.com/watch?v=${urlMatch[1]}`;
    }
    return query;
}

// Helper function to check cooldown
function checkCooldown(userId, commandName) {
    if (!cooldowns.has(userId)) {
        cooldowns.set(userId, new Map());
    }
    
    const userCooldowns = cooldowns.get(userId);
    const now = Date.now();
    
    if (userCooldowns.has(commandName)) {
        const expirationTime = userCooldowns.get(commandName) + COOLDOWN_TIME;
        if (now < expirationTime) {
            const timeLeft = Math.ceil((expirationTime - now) / 1000);
            return { onCooldown: true, timeLeft };
        }
    }
    
    userCooldowns.set(commandName, now);
    setTimeout(() => userCooldowns.delete(commandName), COOLDOWN_TIME);
    return { onCooldown: false };
}

// Helper function to check if user is in voice channel with bot
function isUserInBotVoiceChannel(member, guildId) {
    const player = client.lavalink.players.get(guildId);
    if (!player) return false;
    
    const botVoiceChannelId = player.voiceChannelId;
    const userVoiceChannelId = member.voice.channel?.id;
    
    return userVoiceChannelId === botVoiceChannelId;
}

// Helper function to check if bot can leave (no queue or nothing playing)
function canBotLeave(guildId) {
    const player = client.lavalink.players.get(guildId);
    if (!player) return true;
    
    // Bot can leave if nothing is playing and queue is empty
    return !player.queue.current && player.queue.tracks.length === 0;
}

// Helper function to check if bot is alone in voice channel
function isBotAloneInVoice(guildId) {
    const player = client.lavalink.players.get(guildId);
    if (!player || !player.voiceChannelId) return false;
    
    const guild = client.guilds.cache.get(guildId);
    if (!guild) return false;
    
    const voiceChannel = guild.channels.cache.get(player.voiceChannelId);
    if (!voiceChannel) return false;
    
    // Count non-bot members in voice channel
    const members = voiceChannel.members.filter(m => !m.user.bot);
    return members.size === 0;
}

// Helper function to start inactivity timer
function startInactivityTimer(guildId) {
    // Clear existing timer
    if (inactivityTimers.has(guildId)) {
        clearTimeout(inactivityTimers.get(guildId));
    }
    
    // Set new timer
    const timer = setTimeout(async () => {
        const player = client.lavalink.players.get(guildId);
        if (player) {
            console.log(`⏱️ Inactivity timeout reached for guild ${guildId}`);
            player.queue.tracks = [];
            player.queue.previous = [];
            await player.destroy();
            

        }
        inactivityTimers.delete(guildId);
    }, INACTIVITY_TIMEOUT);
    
    inactivityTimers.set(guildId, timer);
}

// Helper function to reset inactivity timer
function resetInactivityTimer(guildId) {
    startInactivityTimer(guildId);
}

// --- Music Quiz Functions ---
function fuzzyMatch(input, answers) {
    const normalizedInput = input.toLowerCase().trim().replace(/[^\w\s]/g, '');
    
    for (const answer of answers) {
        const normalizedAnswer = answer.toLowerCase().trim().replace(/[^\w\s]/g, '');
        
        // Exact match
        if (normalizedInput === normalizedAnswer) return true;
        
        // Contains match (for partial answers)
        if (normalizedInput.includes(normalizedAnswer) || normalizedAnswer.includes(normalizedInput)) {
            if (normalizedInput.length >= 3) return true;
        }
        
        // Levenshtein distance for typos (allow ~20% error)
        const maxDistance = Math.floor(normalizedAnswer.length * 0.2);
        if (levenshteinDistance(normalizedInput, normalizedAnswer) <= maxDistance) return true;
    }
    return false;
}

function levenshteinDistance(str1, str2) {
    const m = str1.length, n = str2.length;
    const dp = Array.from({ length: m + 1 }, () => Array(n + 1).fill(0));
    
    for (let i = 0; i <= m; i++) dp[i][0] = i;
    for (let j = 0; j <= n; j++) dp[0][j] = j;
    
    for (let i = 1; i <= m; i++) {
        for (let j = 1; j <= n; j++) {
            if (str1[i - 1] === str2[j - 1]) {
                dp[i][j] = dp[i - 1][j - 1];
            } else {
                dp[i][j] = 1 + Math.min(dp[i - 1][j], dp[i][j - 1], dp[i - 1][j - 1]);
            }
        }
    }
    return dp[m][n];
}

async function startQuizRound(guildId, channel) {
    const quiz = activeQuizzes.get(guildId);
    if (!quiz) return;

    quiz.currentRound++;
    quiz.roundActive = true;
    quiz.answered = new Set();
    
    // Initialize played songs tracker if not exists
    if (!quiz.playedSongTitles) {
        quiz.playedSongTitles = new Set();
    }

    // Get the song for this round, skipping already played songs
    let songIndex = quiz.currentRound - 1;
    if (songIndex >= quiz.songs.length || quiz.currentRound > quiz.totalRounds) {
        return endQuiz(guildId, channel);
    }

    // Find a song that hasn't been played yet
    let song = null;
    let foundUnplayedSong = false;
    
    for (let i = songIndex; i < quiz.songs.length; i++) {
        const candidate = quiz.songs[i];
        const titleKey = candidate.title.toLowerCase().trim();
        
        if (!quiz.playedSongTitles.has(titleKey)) {
            song = candidate;
            songIndex = i;
            foundUnplayedSong = true;
            break;
        }
    }
    
    if (!foundUnplayedSong || !song) {
        console.log('Quiz: No more unplayed songs available');
        return endQuiz(guildId, channel);
    }

    let attempts = 0;
    const maxAttempts = 3;

    // Try to play the song, with retry logic using backup songs
    while (attempts < maxAttempts) {
        const currentSongIndex = songIndex + attempts;
        
        if (currentSongIndex >= quiz.songs.length) {
            break; // No more songs to try
        }
        
        song = quiz.songs[currentSongIndex];
        const titleKey = song.title.toLowerCase().trim();
        
        // Skip if already played
        if (quiz.playedSongTitles.has(titleKey)) {
            attempts++;
            continue;
        }

        try {
            // Play the track directly (already fetched)
            if (song.track) {
                await quiz.player.queue.add(song.track);
                if (!quiz.player.playing) {
                    await quiz.player.play();
                }
                // Mark this song as played
                quiz.playedSongTitles.add(titleKey);
                break; // Success!
            } else {
                console.log(`Quiz: Song "${song.title}" has no track, skipping...`);
                attempts++;
            }
        } catch (err) {
            console.error(`Quiz play error for "${song.title}":`, err.message);
            attempts++;
        }
    }

    // Check if we managed to play something
    if (!quiz.player.queue.current && !quiz.player.playing) {
        await channel.send('⚠️ Failed to play songs. Ending quiz...');
        return endQuiz(guildId, channel);
    }

    // If we had to skip songs, update the songs array
    if (attempts > 0) {
        quiz.songs.splice(songIndex, attempts);
    }

    try {
        // Send round embed
        const genreEmojis = { pop: '🎤', anime: '🎌', romance: '💕', rock: '🎸', rnb: '🎵', hiphop: '🔥', edm: '🎧' };
        const genreEmoji = genreEmojis[quiz.genre] || '🎵';
        const isAnime = quiz.genre === 'anime' || quiz.genre === 'romance';
        const roundEmbed = new EmbedBuilder()
            .setAuthor({ name: '🦁 LionBeats Music Quiz', iconURL: 'https://cdn.discordapp.com/emojis/741605543046807626.png' })
            .setTitle(`${genreEmoji} Round ${quiz.currentRound}/${quiz.totalRounds}`)
            .setDescription(isAnime 
                ? '🎵 **Listen and guess!**\n\n> Type the **song name**, **artist**, or **anime name** in chat!\n> First 3 correct answers score points!'
                : '🎵 **Listen and guess!**\n\n> Type the **song name** or **artist** in chat!\n> First 3 correct answers score points!')
            .setColor('#5865F2')
            .addFields({ name: '⏱️ Time Remaining', value: '30 seconds', inline: true })
            .setFooter({ text: 'Type your answer in chat!' });

        const stopButton = new ActionRowBuilder().addComponents(
            new ButtonBuilder()
                .setCustomId('quiz_stop')
                .setLabel('Stop Quiz')
                .setStyle(ButtonStyle.Danger)
                .setEmoji('⏹️')
        );

        await channel.send({ embeds: [roundEmbed], components: [stopButton] });

        // Create message collector for answers
        const filter = m => !m.author.bot && !quiz.answered.has(m.author.id);
        const collector = channel.createMessageCollector({ filter, time: 30000 });
        quiz.messageCollector = collector;

        let winnersThisRound = [];

        collector.on('collect', async (message) => {
            if (fuzzyMatch(message.content, song.answers)) {
                quiz.answered.add(message.author.id);
                
                const place = winnersThisRound.length + 1;
                if (place <= 3) {
                    const points = place === 1 ? 3 : place === 2 ? 2 : 1;
                    const currentScore = quiz.scores.get(message.author.id) || 0;
                    quiz.scores.set(message.author.id, currentScore + points);
                    
                    const medals = ['🥇', '🥈', '🥉'];
                    const placeNames = ['1st', '2nd', '3rd'];
                    winnersThisRound.push({ user: message.author, place, points });
                    
                    // Delete the correct answer so others can't copy
                    await message.delete().catch(() => {});
                    
                    // Announce who got it right
                    const announceEmbed = new EmbedBuilder()
                        .setDescription(`${medals[place - 1]} **${message.author.displayName || message.author.username}** was the **${placeNames[place - 1]}** to get it correct! (+${points} pts)`)
                        .setColor(place === 1 ? '#FFD700' : place === 2 ? '#C0C0C0' : '#CD7F32');
                    
                    await channel.send({ embeds: [announceEmbed] });
                    
                    if (place === 3) {
                        collector.stop('threeWinners');
                    }
                }
            }
        });

        collector.on('end', async (collected, reason) => {
            quiz.roundActive = false;
            
            // Reveal answer
            const animeInfo = song.anime ? `\n📺 From: **${song.anime}**` : '';
            const revealEmbed = new EmbedBuilder()
                .setTitle('🎵 Answer Revealed!')
                .setDescription(`**${song.title}** by **${song.artist}**${animeInfo}`)
                .setColor('#2ECC71');

            if (winnersThisRound.length > 0) {
                const winnersText = winnersThisRound
                    .map(w => `${['🥇', '🥈', '🥉'][w.place - 1]} ${w.user.username} (+${w.points} pts)`)
                    .join('\n');
                revealEmbed.addFields({ name: '🏆 Winners', value: winnersText });
            } else {
                revealEmbed.addFields({ name: '😢', value: 'No one got it!' });
            }

            await channel.send({ embeds: [revealEmbed] });

            // Stop current track
            if (quiz.player && quiz.player.queue.current) {
                await quiz.player.stopPlaying(true);
            }

            // Check if more rounds
            if (quiz.currentRound < quiz.totalRounds && activeQuizzes.has(guildId)) {
                setTimeout(() => startQuizRound(guildId, channel), 3000);
            } else {
                setTimeout(() => endQuiz(guildId, channel), 2000);
            }
        });

    } catch (error) {
        console.error('Quiz round error:', error);
        channel.send('⚠️ Error in quiz round, skipping...');
        setTimeout(() => startQuizRound(guildId, channel), 2000);
    }
}

async function endQuiz(guildId, channel) {
    const quiz = activeQuizzes.get(guildId);
    if (!quiz) return;

    // Clean up
    if (quiz.messageCollector) quiz.messageCollector.stop();
    if (quiz.roundTimeout) clearTimeout(quiz.roundTimeout);

    // Sort scores
    const sortedScores = [...quiz.scores.entries()]
        .sort((a, b) => b[1] - a[1])
        .slice(0, 10);

    const genreEmojis = { pop: '🎤', anime: '🎌', romance: '💕', rock: '🎸', rnb: '🎵', hiphop: '🔥', edm: '🎧' };
    const genreEmoji = genreEmojis[quiz.genre] || '🎵';
    const endEmbed = new EmbedBuilder()
        .setAuthor({ name: '🦁 LionBeats Music Quiz', iconURL: 'https://cdn.discordapp.com/emojis/741605543046807626.png' })
        .setTitle(`${genreEmoji} Quiz Complete!`)
        .setColor('#FFD700');

    if (sortedScores.length > 0) {
        let leaderboardText = '';
        for (let i = 0; i < sortedScores.length; i++) {
            const [userId, score] = sortedScores[i];
            const medal = i === 0 ? '👑' : i === 1 ? '🥈' : i === 2 ? '🥉' : `${i + 1}.`;
            try {
                const user = await client.users.fetch(userId);
                leaderboardText += `${medal} **${user.username}** - ${score} points\n`;
            } catch {
                leaderboardText += `${medal} Unknown User - ${score} points\n`;
            }
        }
        endEmbed.setDescription(`🏆 **Final Leaderboard**\n\n${leaderboardText}`);
        
        if (sortedScores[0]) {
            try {
                const winner = await client.users.fetch(sortedScores[0][0]);
                endEmbed.setFooter({ text: `👑 ${winner.username} wins with ${sortedScores[0][1]} points!` });
            } catch {}
        }
    } else {
        endEmbed.setDescription('No one scored any points! Better luck next time! 😅');
    }

    await channel.send({ embeds: [endEmbed] });
    activeQuizzes.delete(guildId);
}

// Voice state update listener for detecting when bot is alone
client.on('voiceStateUpdate', async (oldState, newState) => {
    // Check if someone left a voice channel
    if (oldState.channelId && oldState.channelId !== newState.channelId) {
        const player = client.lavalink.players.get(oldState.guild.id);
        
        // If the bot is in this channel
        if (player && player.voiceChannelId === oldState.channelId) {
            // Check if bot is now alone
            if (isBotAloneInVoice(oldState.guild.id)) {
                console.log(`🦁 Bot is alone in voice channel, leaving...`);
                player.queue.tracks = [];
                player.queue.previous = [];
                await player.destroy();
                

            }
        }
    }
});

// --- Prefix Command & Message Listener ---
client.on('messageCreate', async (message) => {
    if (message.author.bot) return;

    // Check if this is a locked music channel
    const panelData = musicPanels.get(message.guild.id);
    const isLockedChannel = panelData && message.channel.id === panelData.channelId;

    // If it's a locked channel, check for song requests (URLs or text)
    if (isLockedChannel && !message.content.startsWith(PREFIX) && !message.content.startsWith('/')) {
        const voiceChannel = message.member.voice.channel;
        let shouldDelete = true;
        try {
            if (!voiceChannel) {
                shouldDelete = false;
                return message.reply('🦁 You need to be in a voice channel to request songs!').then(msg => {
                    setTimeout(() => msg.delete().catch(() => {}), 5000);
                });
            }

            // Check if user is in the same voice channel as bot
            const player = client.lavalink.players.get(message.guild.id);
            if (player && !isUserInBotVoiceChannel(message.member, message.guild.id)) {
                shouldDelete = true;
                message.delete().catch(() => {});
                return message.channel.send('🦁 You need to be in the same voice channel as the bot!').then(msg => {
                    setTimeout(() => msg.delete().catch(() => {}), 5000);
                });
            }

            // Check cooldown
            const cooldown = checkCooldown(message.author.id, 'play');
            if (cooldown.onCooldown) {
                shouldDelete = true;
                message.delete().catch(() => {});
                return message.channel.send(`🦁 <@${message.author.id}>, please wait ${cooldown.timeLeft} seconds before requesting another song!`).then(msg => {
                    setTimeout(() => msg.delete().catch(() => {}), 5000);
                });
            }

            // Treat the message as a song request
            const query = message.content.trim();
            let currentPlayer = client.lavalink.players.get(message.guild.id);
            if (!currentPlayer) {
                console.log(`[DEBUG panel-play] Creating player for guild ${message.guild.id}`);
                currentPlayer = client.lavalink.createPlayer({
                    guildId: message.guild.id,
                    voiceChannelId: voiceChannel.id,
                    textChannelId: message.channel.id,
                    selfDeaf: true,
                    selfMute: false,
                    volume: 40 // 40% actual volume = 100% display volume
                });
                currentPlayer.displayVolume = 100; // Track display volume separately
                await currentPlayer.connect();
                console.log(`[DEBUG panel-play] Connected: ${currentPlayer.connected}`);
                startInactivityTimer(message.guild.id); // Start inactivity timer for new player
            }

            const cleanedQuery = cleanYouTubeUrl(query);
            const searchQuery = cleanedQuery.startsWith('http') ? cleanedQuery : `ytsearch:${cleanedQuery}`;
            const result = await currentPlayer.search({ query: searchQuery }, message.author);

            if (!result || !result.tracks || result.tracks.length === 0) {
                shouldDelete = true;
                return message.reply('🦁 No results found!').then(msg => {
                    setTimeout(() => msg.delete().catch(() => {}), 5000);
                });
            }

            // Handle playlists
            if (result.loadType === 'playlist' && result.playlist) {
                await currentPlayer.queue.add(result.tracks);
                console.log(`✅ Playlist added to queue: ${result.playlist.name} (${result.tracks.length} songs)`);
                await message.react('✅').catch(() => {});
            } else {
                // Single track
                const track = result.tracks[0];
                await currentPlayer.queue.add(track);
                console.log(`✅ Song added to queue: ${track.info.title}`);
                await message.react('✅').catch(() => {});
            }

            // Always update the panel after adding a song/playlist
            await updateMusicPanel(message.guild.id);

            // If nothing is playing, start playback
            if (!currentPlayer.playing && !currentPlayer.paused) {
                await currentPlayer.play();
                setTimeout(() => updateMusicPanel(message.guild.id), 100);
            }
        } catch (error) {
            console.error('Error playing from locked channel:', error);
            message.reply('🦁 Failed to play the song!').then(msg => {
                setTimeout(() => msg.delete().catch(() => {}), 5000);
            });
        } finally {
            if (shouldDelete) {
                setTimeout(() => {
                    message.delete().catch(() => {});
                }, 5000);
            }
        }
        return;
    }

    if (!message.content.startsWith(PREFIX)) return;

    const args = message.content.slice(PREFIX.length).trim().split(/ +/);
    const command = args.shift().toLowerCase();

    if (command === 'play') {
        // Check cooldown
        const cooldown = checkCooldown(message.author.id, 'play');
        if (cooldown.onCooldown) {
            return message.reply(`🦁 Please wait ${cooldown.timeLeft} seconds before using this command again!`);
        }

        let query = args.join(' ');
        const voiceChannel = message.member.voice.channel;

        if (!voiceChannel) return message.reply('🦁 You need to be in a voice channel first!');
        if (!query) return message.reply('🦁 Please provide a song name or URL!');

        // Check if user is in the same voice channel as bot
        const existingPlayer = client.lavalink.players.get(message.guild.id);
        if (existingPlayer && !isUserInBotVoiceChannel(message.member, message.guild.id)) {
            return message.reply('🦁 You need to be in the same voice channel as the bot!');
        }

        try {
            let player = client.lavalink.players.get(message.guild.id);
            if (!player) {
                player = client.lavalink.createPlayer({
                    guildId: message.guild.id,
                    voiceChannelId: voiceChannel.id,
                    textChannelId: message.channel.id,
                    selfDeaf: true,
                    selfMute: false,
                    volume: 40 // 40% actual volume = 100% display volume
                });
                player.displayVolume = 100; // Track display volume separately
            }
            
            // Ensure player is connected to voice
            if (!player.connected) {
                await player.connect();
            }

            // Clean YouTube URLs to remove playlist/mix parameters (but keep Spotify playlists)
            if (!query.includes('spotify.com/playlist') && !query.includes('spotify.com/album')) {
                query = cleanYouTubeUrl(query);
            }

            const result = await player.search({ query }, message.author);
            
            if (!result || !result.tracks || result.tracks.length === 0) {
                return message.reply('🦁 No results found! Make sure Lavalink server is running.');
            }

            // Handle playlists
            if (result.loadType === 'playlist' && result.playlist) {
                await player.queue.add(result.tracks);
                if (!player.playing) {
                    await player.play();
                    // Force immediate panel update
                    setTimeout(() => updateMusicPanel(message.guild.id), 100);
                }
                await message.reply(`🦁 Added playlist: **${result.playlist.name}** (${result.tracks.length} songs)`);
            } else {
                // Single track
                await player.queue.add(result.tracks[0]);
                if (!player.playing) {
                    await player.play();
                    // Force immediate panel update
                    setTimeout(() => updateMusicPanel(message.guild.id), 100);
                }
                await message.reply(`🦁 Now playing: **${result.tracks[0].info.title}**`);
            }
        } catch (error) {
            console.error('Play command error:', error);
            const errorMsg = error.message.includes('spotify') 
                ? '🦁 Spotify links are not supported. Please use YouTube links or search terms instead!'
                : '🦁 An error occurred while trying to play the song!';
            message.reply(errorMsg);
        }
    }

    // Stop command
    if (command === 'stop') {
        const cooldown = checkCooldown(message.author.id, 'stop');
        if (cooldown.onCooldown) {
            return message.reply(`🦁 Please wait ${cooldown.timeLeft} seconds before using this command again!`);
        }

        const player = client.lavalink.players.get(message.guild.id);
        
        if (!player) {
            return message.reply('🦁 Nothing is playing!');
        }

        if (!isUserInBotVoiceChannel(message.member, message.guild.id)) {
            return message.reply('🦁 You need to be in the same voice channel as the bot!');
        }

        player.queue.tracks = [];
        player.queue.previous = [];
        await player.destroy();
        await message.reply('🦁 Stopped the music and cleared the queue!');
    }

    // Skip command
    if (command === 'skip') {
        const cooldown = checkCooldown(message.author.id, 'skip');
        if (cooldown.onCooldown) {
            return message.reply(`🦁 Please wait ${cooldown.timeLeft} seconds before using this command again!`);
        }

        const player = client.lavalink.players.get(message.guild.id);
        
        if (!player || !player.queue.current) {
            return message.reply('🦁 Nothing is playing!');
        }

        if (!isUserInBotVoiceChannel(message.member, message.guild.id)) {
            return message.reply('🦁 You need to be in the same voice channel as the bot!');
        }

        await player.skip();
        await message.reply('🦁 Skipped to the next song!');
    }

    // Queue command
    if (command === 'queue') {
        const cooldown = checkCooldown(message.author.id, 'queue');
        if (cooldown.onCooldown) {
            return message.reply(`🦁 Please wait ${cooldown.timeLeft} seconds before using this command again!`);
        }

        const player = client.lavalink.players.get(message.guild.id);
        
        if (!player || !player.queue.current) {
            return message.reply('🦁 The queue is empty!');
        }

        if (!isUserInBotVoiceChannel(message.member, message.guild.id)) {
            return message.reply('🦁 You need to be in the same voice channel as the bot!');
        }

        const current = player.queue.current;
        const queue = player.queue.tracks;

        let queueText = `**Now Playing:**\n${current.info.title}\n\n`;
        
        if (queue.length > 0) {
            queueText += `**Up Next:**\n`;
            queue.slice(0, 10).forEach((track, i) => {
                queueText += `${i + 1}. ${track.info.title}\n`;
            });
            
            if (queue.length > 10) {
                queueText += `\n...and ${queue.length - 10} more tracks`;
            }
        } else {
            queueText += `No more songs in queue`;
        }

        await message.reply(queueText);
    }

    // Now Playing command (np alias)
    if (command === 'nowplaying' || command === 'np') {
        const cooldown = checkCooldown(message.author.id, 'nowplaying');
        if (cooldown.onCooldown) {
            return message.reply(`🦁 Please wait ${cooldown.timeLeft} seconds before using this command again!`);
        }

        const player = client.lavalink.players.get(message.guild.id);
        
        if (!player || !player.queue.current) {
            return message.reply('🦁 Nothing is playing!');
        }

        if (!isUserInBotVoiceChannel(message.member, message.guild.id)) {
            return message.reply('🦁 You need to be in the same voice channel as the bot!');
        }

        const track = player.queue.current;
        const position = player.position;
        const duration = track.info.duration;
        
        const formatTime = (ms) => {
            const seconds = Math.floor((ms / 1000) % 60);
            const minutes = Math.floor((ms / (1000 * 60)) % 60);
            const hours = Math.floor(ms / (1000 * 60 * 60));
            
            if (hours > 0) {
                return `${hours}:${minutes.toString().padStart(2, '0')}:${seconds.toString().padStart(2, '0')}`;
            }
            return `${minutes}:${seconds.toString().padStart(2, '0')}`;
        };

        const nowPlayingText = `**Now Playing:**\n${track.info.title}\n\n` +
            `**Position:** ${formatTime(position)} / ${formatTime(duration)}\n` +
            `**Requested by:** <@${track.requester.id}>`;

        await message.reply(nowPlayingText);
    }
});

// --- Slash Command Handler ---
client.on('interactionCreate', async (interaction) => {
    if (!interaction.isChatInputCommand()) return;

    if (interaction.commandName === 'play') {
        const cooldown = checkCooldown(interaction.user.id, 'play');
        if (cooldown.onCooldown) {
            return interaction.reply({ 
                content: `🦁 Please wait ${cooldown.timeLeft} seconds before using this command again!`, 
                flags: 64 
            });
        }

        let query = interaction.options.getString('query');
        const voiceChannel = interaction.member.voice.channel;

        if (!voiceChannel) {
            return interaction.reply({ 
                content: '🦁 You need to be in a voice channel first!', 
                flags: 64 
            });
        }

        // Check if user is in the same voice channel as bot
        const existingPlayer = client.lavalink.players.get(interaction.guild.id);
        if (existingPlayer && !isUserInBotVoiceChannel(interaction.member, interaction.guild.id)) {
            return interaction.reply({ 
                content: '🦁 You need to be in the same voice channel as the bot!', 
                flags: 64 
            });
        }

        try {
            await interaction.deferReply({ flags: 64 });

            let player = client.lavalink.players.get(interaction.guild.id);
            if (!player) {
                console.log(`[DEBUG /play] Creating new player for guild ${interaction.guild.id}, voice ${voiceChannel.id}`);
                player = client.lavalink.createPlayer({
                    guildId: interaction.guild.id,
                    voiceChannelId: voiceChannel.id,
                    textChannelId: interaction.channel.id,
                    selfDeaf: true,
                    selfMute: false,
                    volume: 40 // 40% actual volume = 100% display volume
                });
                player.displayVolume = 100; // Track display volume separately
            }
            
            // Ensure player is connected to voice
            if (!player.connected) {
                console.log(`[DEBUG /play] Connecting player to voice...`);
                await player.connect();
                console.log(`[DEBUG /play] Connected: ${player.connected}`);
            }

            // Clean YouTube URLs to remove playlist/mix parameters (but keep Spotify playlists)
            if (!query.includes('spotify.com/playlist') && !query.includes('spotify.com/album')) {
                query = cleanYouTubeUrl(query);
            }

            console.log(`[DEBUG /play] Searching for: ${query}`);
            const result = await player.search({ query }, interaction.user);
            console.log(`[DEBUG /play] Search result - loadType: ${result?.loadType}, tracks: ${result?.tracks?.length || 0}`);
            
            if (!result || !result.tracks || result.tracks.length === 0) {
                return interaction.editReply('🦁 No results found! Make sure Lavalink server is running.');
            }

            // Handle playlists
            if (result.loadType === 'playlist' && result.playlist) {
                await player.queue.add(result.tracks);
                if (!player.playing) {
                    await player.play();
                    // Force immediate panel update
                    setTimeout(() => updateMusicPanel(interaction.guild.id), 100);
                }
                await interaction.editReply(`🦁 Added playlist: **${result.playlist.name}** (${result.tracks.length} songs)`);
            } else {
                // Single track
                await player.queue.add(result.tracks[0]);
                if (!player.playing) {
                    await player.play();
                    // Force immediate panel update
                    setTimeout(() => updateMusicPanel(interaction.guild.id), 100);
                }
                await interaction.editReply(`🦁 Now playing: **${result.tracks[0].info.title}**`);
            }
        } catch (error) {
            console.error('Slash play error:', error);
            const errorMsg = error.message.includes('spotify') 
                ? '🦁 Spotify links are not supported. Please use YouTube links or search terms instead!'
                : '🦁 An error occurred while trying to play the song!';
            
            if (interaction.deferred) {
                await interaction.editReply(errorMsg);
            } else {
                await interaction.reply({ content: errorMsg, flags: 64 });
            }
        }
    }

    // Quiz command
    if (interaction.commandName === 'quiz') {
        const guildId = interaction.guild.id;
        
        // Check if quiz already running
        if (activeQuizzes.has(guildId)) {
            return interaction.reply({ 
                content: '🎮 A quiz is already running in this server! Use the stop button to end it.', 
                flags: 64 
            });
        }

        const voiceChannel = interaction.member.voice.channel;
        if (!voiceChannel) {
            return interaction.reply({ 
                content: '🦁 You need to be in a voice channel to start a quiz!', 
                flags: 64 
            });
        }

        const genre = interaction.options.getString('genre');
        const rounds = interaction.options.getInteger('rounds') || 5;
        
        // Defer reply IMMEDIATELY to prevent "No Response" error
        await interaction.deferReply();
        
        try {
            // Create or get player
            let player = client.lavalink.players.get(guildId);
            if (!player) {
                player = client.lavalink.createPlayer({
                    guildId: guildId,
                    voiceChannelId: voiceChannel.id,
                    textChannelId: interaction.channel.id,
                    selfDeaf: true,
                    selfMute: false,
                    volume: 40 // 40% actual volume = 100% display volume
                });
                player.displayVolume = 100; // Track display volume separately
            }
            
            if (!player.connected) {
                await player.connect();
            }

            // Clear existing queue
            player.queue.tracks = [];

            // Show loading message
            const loadingEmbed = new EmbedBuilder()
                .setAuthor({ name: '🦁 LionBeats Music Quiz', iconURL: 'https://cdn.discordapp.com/emojis/741605543046807626.png' })
                .setTitle('🔄 Loading Songs...')
                .setDescription(`Searching for ${genre} songs...\nThis may take a moment!`)
                .setColor('#FFA500');
            
            await interaction.editReply({ embeds: [loadingEmbed] });

            // Fetch songs from YouTube search
            const allSongs = await fetchQuizSongs(player, genre, rounds + 10);

            if (allSongs.length === 0) {
                activeQuizzes.delete(guildId);
                return interaction.editReply('🦁 Failed to load songs! Make sure Lavalink is running.');
            }

            // Select songs for quiz (already shuffled)
            const selectedSongs = allSongs.slice(0, Math.min(rounds + 5, allSongs.length));

            console.log(`Quiz: Selected ${selectedSongs.length} songs for ${rounds} rounds`);

            // Initialize quiz state
            const quizState = {
                genre: genre,
                songs: selectedSongs,
                totalRounds: rounds,
                currentRound: 0,
                scores: new Map(),
                channelId: interaction.channel.id,
                player: player,
                roundActive: false,
                messageCollector: null,
                roundTimeout: null,
                answered: new Set()
            };
            activeQuizzes.set(guildId, quizState);

            // Create start embed
            const genreEmojis = { pop: '🎤', anime: '🎌', romance: '💕', rock: '🎸', rnb: '🎵', hiphop: '🔥', edm: '🎧' };
            const genreNames = { pop: 'Pop', anime: 'Anime', romance: 'Romance Anime', rock: 'Rock', rnb: 'R&B / Soul', hiphop: 'Hip-Hop / Rap', edm: 'EDM / Dance' };
            const genreEmoji = genreEmojis[genre] || '🎵';
            const genreName = genreNames[genre] || genre.charAt(0).toUpperCase() + genre.slice(1);
            const isAnimeQuiz = genre === 'anime' || genre === 'romance';
            const howToPlay = isAnimeQuiz 
                ? '> Listen to the song and type the song name, artist, or anime name'
                : '> Listen to the song and type the song name or artist';
            const startEmbed = new EmbedBuilder()
                .setAuthor({ name: '🦁 LionBeats Music Quiz', iconURL: 'https://cdn.discordapp.com/emojis/741605543046807626.png' })
                .setTitle(`${genreEmoji} ${genreName} Quiz Starting!`)
                .setDescription(`**${rounds} rounds** of music trivia!\n\n🎧 **How to Play:**\n${howToPlay}\n> First correct answer wins the round!\n> 30 seconds per round\n\n🏆 **Scoring:**\n> 🥇 First place: 3 points\n> 🥈 Second place: 2 points\n> 🥉 Third place: 1 point\n\n🎵 *Songs loaded dynamically!*`)
                .setColor('#FF6B6B')
                .setFooter({ text: 'Get ready... First song in 5 seconds!' });

            // Create stop button
            const stopButton = new ActionRowBuilder().addComponents(
                new ButtonBuilder()
                    .setCustomId('quiz_stop')
                    .setLabel('Stop Quiz')
                    .setStyle(ButtonStyle.Danger)
                    .setEmoji('⏹️')
            );

            await interaction.editReply({ embeds: [startEmbed], components: [stopButton] });

            // Start first round after delay
            setTimeout(() => startQuizRound(guildId, interaction.channel), 5000);

        } catch (error) {
            console.error('Quiz start error:', error);
            activeQuizzes.delete(guildId);
            await interaction.editReply('🦁 Failed to start the quiz! Make sure Lavalink is running with Spotify support.').catch(() => {});
        }
    }

    // Stop command
    if (interaction.commandName === 'stop') {
        const cooldown = checkCooldown(interaction.user.id, 'stop');
        if (cooldown.onCooldown) {
            return interaction.reply({ 
                content: `🦁 Please wait ${cooldown.timeLeft} seconds before using this command again!`, 
                flags: 64 
            });
        }

        const player = client.lavalink.players.get(interaction.guild.id);
        
        if (!player) {
            return interaction.reply({ content: '🦁 Nothing is playing!', flags: 64 });
        }

        if (!isUserInBotVoiceChannel(interaction.member, interaction.guild.id)) {
            return interaction.reply({ content: '🦁 You need to be in the same voice channel as the bot!', flags: 64 });
        }

        player.queue.tracks = [];
        player.queue.previous = [];
        await player.destroy();
        await interaction.reply({ content: '🦁 Stopped the music and cleared the queue!', flags: 64 });
    }

    // Skip command
    if (interaction.commandName === 'skip') {
        const cooldown = checkCooldown(interaction.user.id, 'skip');
        if (cooldown.onCooldown) {
            return interaction.reply({ 
                content: `🦁 Please wait ${cooldown.timeLeft} seconds before using this command again!`, 
                flags: 64 
            });
        }

        const player = client.lavalink.players.get(interaction.guild.id);
        
        if (!player || !player.queue.current) {
            return interaction.reply({ content: '🦁 Nothing is playing!', flags: 64 });
        }

        if (!isUserInBotVoiceChannel(interaction.member, interaction.guild.id)) {
            return interaction.reply({ content: '🦁 You need to be in the same voice channel as the bot!', flags: 64 });
        }

        await player.skip();
        await interaction.reply({ content: '🦁 Skipped to the next song!', flags: 64 });
    }

    // Queue command
    if (interaction.commandName === 'queue') {
        const cooldown = checkCooldown(interaction.user.id, 'queue');
        if (cooldown.onCooldown) {
            return interaction.reply({ 
                content: `🦁 Please wait ${cooldown.timeLeft} seconds before using this command again!`, 
                flags: 64 
            });
        }

        const player = client.lavalink.players.get(interaction.guild.id);
        
        if (!player || !player.queue.current) {
            return interaction.reply({ content: '🦁 The queue is empty!', flags: 64 });
        }

        if (!isUserInBotVoiceChannel(interaction.member, interaction.guild.id)) {
            return interaction.reply({ content: '🦁 You need to be in the same voice channel as the bot!', flags: 64 });
        }

        const current = player.queue.current;
        const queue = player.queue.tracks;

        let queueText = `**Now Playing:**\n${current.info.title}\n\n`;
        
        if (queue.length > 0) {
            queueText += `**Up Next:**\n`;
            queue.slice(0, 10).forEach((track, i) => {
                queueText += `${i + 1}. ${track.info.title}\n`;
            });
            
            if (queue.length > 10) {
                queueText += `\n...and ${queue.length - 10} more tracks`;
            }
        } else {
            queueText += `No more songs in queue`;
        }

        await interaction.reply({ content: queueText, flags: 64 });
    }

    // Now Playing command
    if (interaction.commandName === 'nowplaying') {
        const cooldown = checkCooldown(interaction.user.id, 'nowplaying');
        if (cooldown.onCooldown) {
            return interaction.reply({ 
                content: `🦁 Please wait ${cooldown.timeLeft} seconds before using this command again!`, 
                flags: 64 
            });
        }

        const player = client.lavalink.players.get(interaction.guild.id);
        
        if (!player || !player.queue.current) {
            return interaction.reply({ content: '🦁 Nothing is playing!', flags: 64 });
        }

        if (!isUserInBotVoiceChannel(interaction.member, interaction.guild.id)) {
            return interaction.reply({ content: '🦁 You need to be in the same voice channel as the bot!', flags: 64 });
        }

        const track = player.queue.current;
        const position = player.position;
        const duration = track.info.duration;
        
        const formatTime = (ms) => {
            const seconds = Math.floor((ms / 1000) % 60);
            const minutes = Math.floor((ms / (1000 * 60)) % 60);
            const hours = Math.floor(ms / (1000 * 60 * 60));
            
            if (hours > 0) {
                return `${hours}:${minutes.toString().padStart(2, '0')}:${seconds.toString().padStart(2, '0')}`;
            }
            return `${minutes}:${seconds.toString().padStart(2, '0')}`;
        };

        const nowPlayingText = `**Now Playing:**\n${track.info.title}\n\n` +
            `**Position:** ${formatTime(position)} / ${formatTime(duration)}\n` +
            `**Requested by:** <@${track.requester.id}>`;

        await interaction.reply({ content: nowPlayingText, flags: 64 });
    }

    // Lock Channel command
    if (interaction.commandName === 'lock-channel') {
        const cooldown = checkCooldown(interaction.user.id, 'lock-channel');
        if (cooldown.onCooldown) {
            return interaction.reply({ 
                content: `🦁 Please wait ${cooldown.timeLeft} seconds before using this command again!`, 
                flags: 64 
            });
        }

        const channel = interaction.options.getChannel('channel');
        
        if (channel.type !== 0) { // 0 = GUILD_TEXT
            return interaction.reply({ content: '🦁 Please select a text channel!', flags: 64 });
        }

        try {
            // Create the music panel
            const player = client.lavalink.players.get(interaction.guild.id);
            const embed = createMusicEmbed(player);
            const buttons = createControlButtons(player);

            const message = await channel.send({
                embeds: [embed],
                components: buttons
            });

            // Store panel data
            musicPanels.set(interaction.guild.id, {
                channelId: channel.id,
                messageId: message.id
            });
            saveMusicPanels(); // Save to file

            await interaction.reply({
                content: `🦁 Music control panel created in ${channel}!\nYou can now send song requests directly in that channel (links or search terms).\n**Note:** You must be in a voice channel to interact with the panel or request songs!`,
                flags: 64
            });
        } catch (error) {
            console.error('Error creating music panel:', error);
            if (interaction.deferred || interaction.replied) {
                await interaction.editReply('🦁 Failed to create music panel. Make sure I have permission to send messages in that channel!');
            } else {
                await interaction.reply({
                    content: '🦁 Failed to create music panel. Make sure I have permission to send messages in that channel!',
                    flags: 64
                });
            }
        }
    }

    // Unlock Channel command
    if (interaction.commandName === 'unlock-channel') {
        if (!interaction.member.permissions.has('Administrator')) {
            return interaction.reply({ content: '🦁 You need Administrator permission to unlock channels!', flags: 64 });
        }

        const panelData = musicPanels.get(interaction.guild.id);
        if (!panelData) {
            return interaction.reply({ content: '🦁 No locked channel found for this server!', flags: 64 });
        }

        musicPanels.delete(interaction.guild.id);
        saveMusicPanels();

        await interaction.reply({ 
            content: `🔓 Music channel unlocked! The bot will no longer listen for song requests in <#${panelData.channelId}>.`, 
            flags: 64 
        });
    }

    // Loop command
    if (interaction.commandName === 'loop') {
        const cooldown = checkCooldown(interaction.user.id, 'loop');
        if (cooldown.onCooldown) {
            return interaction.reply({ 
                content: `🦁 Please wait ${cooldown.timeLeft} seconds before using this command again!`, 
                flags: 64 
            });
        }

        if (!isUserInBotVoiceChannel(interaction.member, interaction.guild.id)) {
            return interaction.reply({ content: '🦁 You must be in the same voice channel as the bot!', flags: 64 });
        }

        const player = client.lavalink.players.get(interaction.guild.id);
        if (!player || !player.queue.current) {
            return interaction.reply({ content: '🦁 Nothing is playing!', flags: 64 });
        }

        const mode = interaction.options.getString('mode');
        player.setRepeatMode(mode);
        
        const modeText = mode === 'off' ? 'Loop disabled' : mode === 'track' ? 'Looping current track' : 'Looping queue';
        await interaction.reply({ content: `🔁 ${modeText}`, flags: 64 });
        await updateMusicPanel(interaction.guild.id);
    }

    // Clear Queue command
    if (interaction.commandName === 'clearqueue') {
        const cooldown = checkCooldown(interaction.user.id, 'clearqueue');
        if (cooldown.onCooldown) {
            return interaction.reply({ 
                content: `🦁 Please wait ${cooldown.timeLeft} seconds before using this command again!`, 
                flags: 64 
            });
        }

        if (!isUserInBotVoiceChannel(interaction.member, interaction.guild.id)) {
            return interaction.reply({ content: '🦁 You must be in the same voice channel as the bot!', flags: 64 });
        }

        const player = client.lavalink.players.get(interaction.guild.id);
        if (!player) {
            return interaction.reply({ content: '🦁 No active player!', flags: 64 });
        }

        const queueLength = player.queue.tracks.length;
        if (queueLength === 0) {
            return interaction.reply({ content: '🦁 Queue is already empty!', flags: 64 });
        }

        player.queue.tracks = [];
        await interaction.reply({ content: `🗑️ Cleared ${queueLength} track${queueLength !== 1 ? 's' : ''} from queue`, flags: 64 });
        await updateMusicPanel(interaction.guild.id);
    }

    // Volume command
    if (interaction.commandName === 'volume') {
        const cooldown = checkCooldown(interaction.user.id, 'volume');
        if (cooldown.onCooldown) {
            return interaction.reply({ 
                content: `🦁 Please wait ${cooldown.timeLeft} seconds before using this command again!`, 
                flags: 64 
            });
        }

        if (!isUserInBotVoiceChannel(interaction.member, interaction.guild.id)) {
            return interaction.reply({ content: '🦁 You must be in the same voice channel as the bot!', flags: 64 });
        }

        const player = client.lavalink.players.get(interaction.guild.id);
        if (!player || !player.queue.current) {
            return interaction.reply({ content: '🦁 Nothing is playing!', flags: 64 });
        }

        const volume = interaction.options.getInteger('level');
        await player.setVolume(volume);
        await interaction.reply({ content: `🔊 Volume set to ${volume}%`, flags: 64 });
        await updateMusicPanel(interaction.guild.id);
    }

    // Bass Boost command
    if (interaction.commandName === 'bassboost') {
        const cooldown = checkCooldown(interaction.user.id, 'bassboost');
        if (cooldown.onCooldown) {
            return interaction.reply({ 
                content: `🦁 Please wait ${cooldown.timeLeft} seconds before using this command again!`, 
                flags: 64 
            });
        }

        if (!isUserInBotVoiceChannel(interaction.member, interaction.guild.id)) {
            return interaction.reply({ content: '🦁 You must be in the same voice channel as the bot!', flags: 64 });
        }

        const player = client.lavalink.players.get(interaction.guild.id);
        if (!player || !player.queue.current) {
            return interaction.reply({ content: '🦁 Nothing is playing!', flags: 64 });
        }

        const currentBassBoost = bassBoostEnabled.get(interaction.guild.id) || false;
        const newBassBoost = !currentBassBoost;
        
        if (newBassBoost) {
            await player.filterManager.setEQ([
                { band: 0, gain: 0.2 },
                { band: 1, gain: 0.15 },
                { band: 2, gain: 0.1 },
                { band: 3, gain: 0.05 }
            ]);
            bassBoostEnabled.set(interaction.guild.id, true);
            await interaction.reply({ content: `🎚️ Bass boost enabled!`, flags: 64 });
        } else {
            await player.filterManager.clearEQ();
            bassBoostEnabled.set(interaction.guild.id, false);
            await interaction.reply({ content: `🎚️ Bass boost disabled!`, flags: 64 });
        }
        
        await updateMusicPanel(interaction.guild.id);
    }

    // Previous command
    if (interaction.commandName === 'previous') {
        const cooldown = checkCooldown(interaction.user.id, 'previous');
        if (cooldown.onCooldown) {
            return interaction.reply({ 
                content: `🦁 Please wait ${cooldown.timeLeft} seconds before using this command again!`, 
                flags: 64 
            });
        }

        if (!isUserInBotVoiceChannel(interaction.member, interaction.guild.id)) {
            return interaction.reply({ content: '🦁 You must be in the same voice channel as the bot!', flags: 64 });
        }

        const player = client.lavalink.players.get(interaction.guild.id);
        if (!player || !player.queue.current) {
            return interaction.reply({ content: '🦁 Nothing is playing!', flags: 64 });
        }

        if (!player.queue.previous || player.queue.previous.length === 0) {
            return interaction.reply({ content: '🦁 No previous tracks!', flags: 64 });
        }

        // Get the last track from previous queue
        const previousTrack = player.queue.previous[player.queue.previous.length - 1];
        
        // Add current track back to the front of the queue
        if (player.queue.current) {
            player.queue.tracks.unshift(player.queue.current);
        }
        
        // Play the previous track
        await player.play({ track: previousTrack });
        await interaction.reply({ content: `⏮️ Playing previous track: ${previousTrack.info.title}`, flags: 64 });
    }

    // Restart command
    if (interaction.commandName === 'restart') {
        // Check if user has admin permissions
        if (!interaction.member.permissions.has('Administrator')) {
            return interaction.reply({ content: '🦁 You need Administrator permission to restart the bot!', flags: 64 });
        }

        await interaction.reply({ content: '🦁 Restarting bot...', flags: 64 });
        
        console.log('🔄 Bot restart requested by', interaction.user.tag);
        process.exit(0);
    }

    // Set Activity command - Show modal for passcode
    if (interaction.commandName === 'set-activity') {
        // Check if user has admin permissions
        if (!interaction.member.permissions.has('Administrator')) {
            return interaction.reply({ content: '🦁 You need Administrator permission to use this command!', flags: 64 });
        }

        const activity = interaction.options.getString('activity');
        const type = interaction.options.getString('type') || 'listening';

        // Create modal for passcode
        const modal = new ModalBuilder()
            .setCustomId(`activity_passcode_${activity}_${type}`)
            .setTitle('🔐 Additional Security Required');

        const passcodeInput = new TextInputBuilder()
            .setCustomId('passcode_input')
            .setLabel('Enter Admin Passcode')
            .setStyle(TextInputStyle.Short)
            .setPlaceholder('Enter the 6-digit passcode')
            .setRequired(true)
            .setMinLength(6)
            .setMaxLength(6);

        const actionRow = new ActionRowBuilder().addComponents(passcodeInput);
        modal.addComponents(actionRow);

        await interaction.showModal(modal);
    }

    // Set Default command - Show modal for passcode
    if (interaction.commandName === 'set-default') {
        // Check if user has admin permissions
        if (!interaction.member.permissions.has('Administrator')) {
            return interaction.reply({ content: '🦁 You need Administrator permission to use this command!', flags: 64 });
        }

        // Create modal for passcode
        const modal = new ModalBuilder()
            .setCustomId('default_passcode')
            .setTitle('🔐 Additional Security Required');

        const passcodeInput = new TextInputBuilder()
            .setCustomId('passcode_input')
            .setLabel('Enter Admin Passcode')
            .setStyle(TextInputStyle.Short)
            .setPlaceholder('Enter the 6-digit passcode')
            .setRequired(true)
            .setMinLength(6)
            .setMaxLength(6);

        const actionRow = new ActionRowBuilder().addComponents(passcodeInput);
        modal.addComponents(actionRow);

        await interaction.showModal(modal);
    }
});

// Modal submission handler for activity commands
client.on('interactionCreate', async (interaction) => {
    if (!interaction.isModalSubmit()) return;

    // Handle set-activity modal
    if (interaction.customId.startsWith('activity_passcode_')) {
        const passcode = interaction.fields.getTextInputValue('passcode_input');
        
        if (passcode !== '146332') {
            return interaction.reply({ content: '🦁 Invalid passcode!', flags: 64 });
        }

        // Parse activity and type from customId
        const parts = interaction.customId.replace('activity_passcode_', '').split('_');
        const type = parts.pop();
        const activity = parts.join('_');

        // Map activity type string to ActivityType enum
        const activityTypes = {
            'playing': ActivityType.Playing,
            'listening': ActivityType.Listening,
            'watching': ActivityType.Watching,
            'competing': ActivityType.Competing
        };

        try {
            client.user.setPresence({
                activities: [{ name: activity, type: activityTypes[type] }],
                status: 'online'
            });

            const typeEmoji = { playing: '🎮', listening: '🎵', watching: '📺', competing: '🏆' };
            await interaction.reply({ 
                content: `🦁 Bot activity updated!\n${typeEmoji[type]} **${type.charAt(0).toUpperCase() + type.slice(1)}:** ${activity}`, 
                flags: 64 
            });
            console.log(`🎭 Activity changed to "${activity}" by ${interaction.user.tag}`);
        } catch (error) {
            console.error('Error setting activity:', error);
            await interaction.reply({ content: '🦁 Failed to update activity!', flags: 64 });
        }
    }

    // Handle set-default modal
    if (interaction.customId === 'default_passcode') {
        const passcode = interaction.fields.getTextInputValue('passcode_input');
        
        if (passcode !== '146332') {
            return interaction.reply({ content: '🦁 Invalid passcode!', flags: 64 });
        }

        try {
            client.user.setPresence({
                activities: [{ name: 'LionBeatsGG 🎵', type: ActivityType.Listening }],
                status: 'online'
            });

            await interaction.reply({ 
                content: '🦁 Bot activity reset to default!\n🎵 **Listening to:** LionBeatsGG 🎵', 
                flags: 64 
            });
            console.log(`🎭 Activity reset to default by ${interaction.user.tag}`);
        } catch (error) {
            console.error('Error resetting activity:', error);
            await interaction.reply({ content: '🦁 Failed to reset activity!', flags: 64 });
        }
    }
});

// Button interaction handler
client.on('interactionCreate', async (interaction) => {
    if (!interaction.isButton()) return;

    const guildId = interaction.guild.id;
    const player = client.lavalink.players.get(guildId);

    // Handle quiz stop button separately (doesn't require voice channel)
    if (interaction.customId === 'quiz_stop') {
        const quiz = activeQuizzes.get(guildId);
        if (!quiz) {
            return interaction.reply({ content: '🎮 No quiz is currently running!', flags: 64 });
        }

        // Stop the quiz
        if (quiz.messageCollector) quiz.messageCollector.stop('stopped');
        if (quiz.player && quiz.player.queue.current) {
            await quiz.player.stopPlaying(true);
        }
        
        const channel = interaction.channel;
        activeQuizzes.delete(guildId);
        
        await interaction.reply({ content: '⏹️ Quiz stopped!', flags: 64 });
        
        const stopEmbed = new EmbedBuilder()
            .setAuthor({ name: '🦁 LionBeats Music Quiz', iconURL: 'https://cdn.discordapp.com/emojis/741605543046807626.png' })
            .setTitle('🛑 Quiz Ended Early')
            .setDescription('The quiz was stopped by a user.')
            .setColor('#E74C3C');
        
        await channel.send({ embeds: [stopEmbed] });
        return;
    }

    // Check if user is in voice channel with bot
    if (!isUserInBotVoiceChannel(interaction.member, guildId)) {
        return interaction.reply({ 
            content: '🦁 You need to be in the same voice channel as the bot to use controls!', 
            flags: 64 
        });
    }

    try {
        switch (interaction.customId) {
            case 'music_playpause':
                const playpauseCooldown = checkCooldown(interaction.user.id, 'button_playpause');
                if (playpauseCooldown.onCooldown) {
                    return interaction.reply({ 
                        content: `🦁 Please wait ${playpauseCooldown.timeLeft} seconds!`, 
                        flags: 64 
                    });
                }

                if (!player || !player.queue.current) {
                    return interaction.reply({ content: '🦁 Nothing is playing!', flags: 64 });
                }
                
                if (player.paused) {
                    await player.resume();
                    await interaction.reply({ content: '▶️ Resumed', flags: 64 });
                } else {
                    await player.pause();
                    await interaction.reply({ content: '⏸️ Paused', flags: 64 });
                }
                
                // Small delay to ensure player state is updated
                setTimeout(async () => {
                    await updateMusicPanel(guildId);
                }, 300);
                break;

            case 'music_stop':
                const stopCooldown = checkCooldown(interaction.user.id, 'button_stop');
                if (stopCooldown.onCooldown) {
                    return interaction.reply({ 
                        content: `🦁 Please wait ${stopCooldown.timeLeft} seconds!`, 
                        flags: 64 
                    });
                }

                if (!player) {
                    return interaction.reply({ content: '🦁 Nothing is playing!', flags: 64 });
                }
                
                player.queue.tracks = [];
                player.queue.previous = [];
                await player.destroy();
                await interaction.reply({ content: '⏹️ Stopped and cleared queue', flags: 64 });
                await updateMusicPanel(guildId);
                break;

            case 'music_skip':
                const skipCooldown = checkCooldown(interaction.user.id, 'button_skip');
                if (skipCooldown.onCooldown) {
                    return interaction.reply({ 
                        content: `🦁 Please wait ${skipCooldown.timeLeft} seconds!`, 
                        flags: 64 
                    });
                }

                if (!player || !player.queue.current) {
                    return interaction.reply({ content: '🦁 Nothing is playing!', flags: 64 });
                }
                
                // Stop the current track - if there's a next track it will auto-play
                if (player.queue.tracks.length > 0) {
                    await player.skip();
                    await interaction.reply({ content: '⏭️ Skipped', flags: 64 });
                } else {
                    // No next track, just stop the current one
                    await player.stopPlaying(true);
                    await interaction.reply({ content: '⏭️ Skipped (queue is now empty)', flags: 64 });
                    setTimeout(async () => {
                        await updateMusicPanel(guildId);
                    }, 300);
                }
                break;

            case 'music_queue':
                const queueCooldown = checkCooldown(interaction.user.id, 'button_queue');
                if (queueCooldown.onCooldown) {
                    return interaction.reply({ 
                        content: `🦁 Please wait ${queueCooldown.timeLeft} seconds!`, 
                        flags: 64 
                    });
                }

                if (!player || !player.queue.current) {
                    return interaction.reply({ content: '🦁 The queue is empty!', flags: 64 });
                }

                const current = player.queue.current;
                const queue = player.queue.tracks;

                let queueText = `**Now Playing:**\n${current.info.title}\n\n`;
                
                if (queue.length > 0) {
                    queueText += `**Up Next:**\n`;
                    queue.slice(0, 10).forEach((track, i) => {
                        queueText += `${i + 1}. ${track.info.title}\n`;
                    });
                    
                    if (queue.length > 10) {
                        queueText += `\n...and ${queue.length - 10} more tracks`;
                    }
                } else {
                    queueText += `No more songs in queue`;
                }

                await interaction.reply({ content: queueText, flags: 64 });
                break;

            case 'music_loop':
                const loopCooldown = checkCooldown(interaction.user.id, 'button_loop');
                if (loopCooldown.onCooldown) {
                    return interaction.reply({ 
                        content: `🦁 Please wait ${loopCooldown.timeLeft} seconds!`, 
                        flags: 64 
                    });
                }

                if (!player || !player.queue.current) {
                    return interaction.reply({ content: '🦁 Nothing is playing!', flags: 64 });
                }

                // Cycle through loop modes: off -> track -> queue -> off
                let newMode = 'off';
                if (!player.repeatMode || player.repeatMode === 'off') {
                    newMode = 'track';
                } else if (player.repeatMode === 'track') {
                    newMode = 'queue';
                } else {
                    newMode = 'off';
                }

                player.setRepeatMode(newMode);
                const modeText = newMode === 'off' ? 'Loop disabled' : newMode === 'track' ? 'Looping current track' : 'Looping queue';
                await interaction.reply({ content: `🔁 ${modeText}`, flags: 64 });
                await updateMusicPanel(guildId);
                break;

            case 'music_clearqueue':
                const clearCooldown = checkCooldown(interaction.user.id, 'button_clearqueue');
                if (clearCooldown.onCooldown) {
                    return interaction.reply({ 
                        content: `🦁 Please wait ${clearCooldown.timeLeft} seconds!`, 
                        flags: 64 
                    });
                }

                if (!player) {
                    return interaction.reply({ content: '🦁 No active player!', flags: 64 });
                }

                const queueLength = player.queue.tracks.length;
                if (queueLength === 0) {
                    return interaction.reply({ content: '🦁 Queue is already empty!', flags: 64 });
                }

                player.queue.tracks = [];
                await interaction.reply({ content: `🗑️ Cleared ${queueLength} track${queueLength !== 1 ? 's' : ''} from queue`, flags: 64 });
                await updateMusicPanel(guildId);
                break;

            case 'music_volume':
                const volumeCooldown = checkCooldown(interaction.user.id, 'button_volume');
                if (volumeCooldown.onCooldown) {
                    return interaction.reply({ 
                        content: `🦁 Please wait ${volumeCooldown.timeLeft} seconds!`, 
                        flags: 64 
                    });
                }

                if (!player || !player.queue.current) {
                    return interaction.reply({ content: '🦁 Nothing is playing!', flags: 64 });
                }

                // Cycle through display volume levels: 100 -> 75 -> 50 -> 25 -> 100
                // Actual volume is scaled to 60% max (so 100% display = 60% actual)
                const currentDisplayVol = player.displayVolume || 100;
                let newDisplayVol = 100;
                if (currentDisplayVol === 100) newDisplayVol = 75;
                else if (currentDisplayVol === 75) newDisplayVol = 50;
                else if (currentDisplayVol === 50) newDisplayVol = 25;
                else newDisplayVol = 100;

                const actualVolume = Math.round(newDisplayVol * 0.4); // Scale to 40% max
                player.displayVolume = newDisplayVol;
                await player.setVolume(actualVolume);
                await interaction.reply({ content: `🔊 Volume set to ${newDisplayVol}%`, flags: 64 });
                await updateMusicPanel(guildId);
                break;

            case 'music_previous':
                const prevCooldown = checkCooldown(interaction.user.id, 'button_previous');
                if (prevCooldown.onCooldown) {
                    return interaction.reply({ 
                        content: `🦁 Please wait ${prevCooldown.timeLeft} seconds!`, 
                        flags: 64 
                    });
                }

                if (!player || !player.queue.current) {
                    return interaction.reply({ content: '🦁 Nothing is playing!', flags: 64 });
                }

                if (!player.queue.previous || player.queue.previous.length === 0) {
                    return interaction.reply({ content: '🦁 No previous tracks!', flags: 64 });
                }

                const previousTrack = player.queue.previous[player.queue.previous.length - 1];
                
                if (player.queue.current) {
                    player.queue.tracks.unshift(player.queue.current);
                }
                
                await player.play({ track: previousTrack });
                await interaction.reply({ content: `⏮️ Playing previous track`, flags: 64 });
                break;

            case 'music_bassboost':
                const bassBoostCooldown = checkCooldown(interaction.user.id, 'button_bassboost');
                if (bassBoostCooldown.onCooldown) {
                    return interaction.reply({ 
                        content: `🦁 Please wait ${bassBoostCooldown.timeLeft} seconds!`, 
                        flags: 64 
                    });
                }

                if (!player || !player.queue.current) {
                    return interaction.reply({ content: '🦁 Nothing is playing!', flags: 64 });
                }

                // Defer reply immediately to avoid timeout
                await interaction.deferReply({ flags: 64 });

                const currentBassBoost = bassBoostEnabled.get(guildId) || false;
                const newBassBoost = !currentBassBoost;
                
                try {
                    if (newBassBoost) {
                        // Enable bass boost
                        await player.filterManager.setEQ([
                            { band: 0, gain: 0.2 },
                            { band: 1, gain: 0.15 },
                            { band: 2, gain: 0.1 },
                            { band: 3, gain: 0.05 }
                        ]);
                        bassBoostEnabled.set(guildId, true);
                        await interaction.editReply({ content: `🎚️ Bass boost enabled!` });
                    } else {
                        // Disable bass boost
                        await player.filterManager.clearEQ();
                        bassBoostEnabled.set(guildId, false);
                        await interaction.editReply({ content: `🎚️ Bass boost disabled!` });
                    }
                } catch (filterError) {
                    console.error('Bass boost filter error:', filterError);
                    await interaction.editReply({ content: `🦁 Failed to change bass boost!` });
                }
                
                // Small delay to ensure state is updated
                setTimeout(async () => {
                    await updateMusicPanel(guildId);
                }, 300);
                break;

            case 'music_lyrics':
                const lyricsCooldown = checkCooldown(interaction.user.id, 'button_lyrics');
                if (lyricsCooldown.onCooldown) {
                    return interaction.reply({ 
                        content: `🦁 Please wait ${lyricsCooldown.timeLeft} seconds!`, 
                        flags: 64 
                    });
                }

                if (!player || !player.queue.current) {
                    return interaction.reply({ content: '🦁 Nothing is playing!', flags: 64 });
                }

                await interaction.deferReply({ flags: 64 });

                try {
                    const currentTrack = player.queue.current;
                    const trackTitle = currentTrack.info.title;
                    const trackAuthor = currentTrack.info.author;

                    // Clean up the title for better search results
                    let cleanTitle = trackTitle
                        .replace(/\(Official.*?\)/gi, '')
                        .replace(/\[Official.*?\]/gi, '')
                        .replace(/\(Lyrics.*?\)/gi, '')
                        .replace(/\[Lyrics.*?\]/gi, '')
                        .replace(/\(Audio.*?\)/gi, '')
                        .replace(/\[Audio.*?\]/gi, '')
                        .replace(/\(Music Video.*?\)/gi, '')
                        .replace(/\[Music Video.*?\]/gi, '')
                        .replace(/\(Visualizer.*?\)/gi, '')
                        .replace(/\[Visualizer.*?\]/gi, '')
                        .replace(/\(Lyric Video.*?\)/gi, '')
                        .replace(/\[Lyric Video.*?\]/gi, '')
                        .replace(/\(Video.*?\)/gi, '')
                        .replace(/\[Video.*?\]/gi, '')
                        .replace(/\(Explicit.*?\)/gi, '')
                        .replace(/\[Explicit.*?\]/gi, '')
                        .replace(/HD|HQ|4K|MV|M\/V/gi, '')
                        .replace(/\s+/g, ' ')
                        .trim();

                    // Clean up the artist name
                    let cleanArtist = trackAuthor
                        .replace(/- Topic$/i, '')
                        .replace(/VEVO$/i, '')
                        .replace(/Official$/i, '')
                        .trim();

                    // Try to extract artist from title if it contains " - "
                    let searchArtist = cleanArtist;
                    let searchTitle = cleanTitle;
                    
                    if (cleanTitle.includes(' - ')) {
                        const parts = cleanTitle.split(' - ');
                        searchArtist = parts[0].trim();
                        searchTitle = parts.slice(1).join(' - ').trim();
                    }

                    // Remove featuring artists from title for cleaner search
                    searchTitle = searchTitle
                        .replace(/\s*[\(\[]?fe?a?t\.?\s+[^\)\]]+[\)\]]?/gi, '')
                        .replace(/\s*[\(\[]?with\s+[^\)\]]+[\)\]]?/gi, '')
                        .replace(/\s*[\(\[]?ft\.?\s+[^\)\]]+[\)\]]?/gi, '')
                        .trim();

                    let lyrics = null;

                    // Try lrclib.net API first (free, no API key needed)
                    try {
                        const lrclibUrl = `https://lrclib.net/api/search?track_name=${encodeURIComponent(searchTitle)}&artist_name=${encodeURIComponent(searchArtist)}`;
                        const lrclibResponse = await fetch(lrclibUrl, {
                            headers: { 'User-Agent': 'LionBeatsGG Discord Bot' }
                        });
                        
                        if (lrclibResponse.ok) {
                            const lrclibData = await lrclibResponse.json();
                            if (lrclibData && lrclibData.length > 0 && lrclibData[0].plainLyrics) {
                                lyrics = lrclibData[0].plainLyrics;
                            }
                        }
                    } catch (e) {
                        console.log('lrclib.net failed, trying fallback...');
                    }

                    // Fallback: Try with just the title
                    if (!lyrics) {
                        try {
                            const fallbackUrl = `https://lrclib.net/api/search?q=${encodeURIComponent(searchTitle + ' ' + searchArtist)}`;
                            const fallbackResponse = await fetch(fallbackUrl, {
                                headers: { 'User-Agent': 'LionBeatsGG Discord Bot' }
                            });
                            
                            if (fallbackResponse.ok) {
                                const fallbackData = await fallbackResponse.json();
                                if (fallbackData && fallbackData.length > 0 && fallbackData[0].plainLyrics) {
                                    lyrics = fallbackData[0].plainLyrics;
                                }
                            }
                        } catch (e) {
                            console.log('Fallback search also failed');
                        }
                    }

                    // Second fallback: Try lyrist API
                    if (!lyrics) {
                        try {
                            const lyristUrl = `https://lyrist.vercel.app/api/${encodeURIComponent(searchTitle)}/${encodeURIComponent(searchArtist)}`;
                            const lyristResponse = await fetch(lyristUrl);
                            
                            if (lyristResponse.ok) {
                                const lyristData = await lyristResponse.json();
                                if (lyristData && lyristData.lyrics) {
                                    lyrics = lyristData.lyrics;
                                }
                            }
                        } catch (e) {
                            console.log('Lyrist API also failed');
                        }
                    }

                    if (!lyrics) {
                        return interaction.editReply({ 
                            content: `📝 **Lyrics not found**\n\n🎵 **${trackTitle}**\nby ${trackAuthor}\n\n_Searched for: "${searchTitle}" by "${searchArtist}"_\n_Try a more popular song or check the song name._` 
                        });
                    }

                    // Clean up lyrics
                    lyrics = lyrics.replace(/\r\n/g, '\n').trim();
                    
                    // Split lyrics into chunks if too long (Discord embed limit)
                    if (lyrics.length > 4000) {
                        lyrics = lyrics.substring(0, 3900) + '\n\n... *(lyrics truncated)*';
                    }

                    const lyricsEmbed = new EmbedBuilder()
                        .setAuthor({ name: '🦁 LionBeats Lyrics', iconURL: 'https://cdn.discordapp.com/emojis/741605543046807626.png' })
                        .setTitle(`📝 ${searchTitle}`)
                        .setDescription(lyrics)
                        .setColor('#5865F2')
                        .setFooter({ text: `${searchArtist} • Requested by ${interaction.user.username}` });

                    await interaction.editReply({ embeds: [lyricsEmbed] });

                } catch (lyricsError) {
                    console.error('Lyrics fetch error:', lyricsError);
                    await interaction.editReply({ 
                        content: `🦁 Failed to fetch lyrics. Please try again later.` 
                    });
                }
                break;
        }
    } catch (error) {
        console.error('Button interaction error:', error);
        if (!interaction.replied && !interaction.deferred) {
            await interaction.reply({ content: '🦁 An error occurred!', flags: 64 }).catch(() => {});
        }
    }
});

// Update panel when track starts
client.lavalink.on('trackStart', async (player, track) => {
    const quiz = activeQuizzes.get(player.guildId);
    
    // Use different console messages for quiz vs normal playback
    if (quiz && quiz.roundActive) {
        console.log(`🎮 Quiz Playing: ${track.info.title}`);
        // Don't update music panel during quiz to hide song info
    } else {
        console.log(`🎵 Track Playing: ${track.info.title}`);
        
        // Track play history and statistics (not during quiz)
        const guild = client.guilds.cache.get(player.guildId);
        addToPlayHistory(track, player.guildId, guild?.name || 'Unknown Server');
        
        // Small delay to ensure player state is fully updated
        setTimeout(async () => {
            await updateMusicPanel(player.guildId);
        }, 500);
    }
    
    resetInactivityTimer(player.guildId); // Reset inactivity timer when track starts
});

// Update panel when track ends
client.lavalink.on('trackEnd', async (player) => {
    const quiz = activeQuizzes.get(player.guildId);
    
    // Don't update music panel during quiz
    if (!quiz || !quiz.roundActive) {
        await updateMusicPanel(player.guildId);
    }
    
    // If queue is empty, start inactivity timer
    if (!player.queue.current && player.queue.tracks.length === 0) {
        startInactivityTimer(player.guildId);
    }
});

// Handle track errors (e.g. YouTube stream failures)
client.lavalink.on('trackError', async (player, track, payload) => {
    console.error(`Track error for "${track?.info?.title}": ${payload?.message || payload?.exception?.message || 'Unknown error'}`);
    const panelData = musicPanels.get(player.guildId);
    if (panelData) {
        try {
            const channel = await client.channels.fetch(panelData.channelId).catch(() => null);
            if (channel) {
                channel.send(`🦁 Failed to play **${track?.info?.title || 'Unknown'}** - skipping...`).then(msg => {
                    setTimeout(() => msg.delete().catch(() => {}), 8000);
                });
            }
        } catch (e) { /* ignore */ }
    }
    await updateMusicPanel(player.guildId);
});

// Handle stuck tracks
client.lavalink.on('trackStuck', async (player, track, payload) => {
    console.warn(`Track stuck: "${track?.info?.title}" (threshold: ${payload?.thresholdMs}ms)`);
    const panelData = musicPanels.get(player.guildId);
    if (panelData) {
        try {
            const channel = await client.channels.fetch(panelData.channelId).catch(() => null);
            if (channel) {
                channel.send(`🦁 Track got stuck: **${track?.info?.title || 'Unknown'}** - skipping...`).then(msg => {
                    setTimeout(() => msg.delete().catch(() => {}), 8000);
                });
            }
        } catch (e) { /* ignore */ }
    }
    await updateMusicPanel(player.guildId);
});

// Handle empty queue
client.lavalink.on('queueEnd', async (player) => {
    console.log(`Queue ended for guild ${player.guildId}`);
    await updateMusicPanel(player.guildId);
    startInactivityTimer(player.guildId);
});

client.login(process.env.DISCORD_TOKEN);
