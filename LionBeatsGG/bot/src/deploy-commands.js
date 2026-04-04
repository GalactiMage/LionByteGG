import 'dotenv/config';
import fs from 'fs';
import path from 'path';
import { fileURLToPath } from 'url';
import { REST, Routes, SlashCommandBuilder } from 'discord.js';

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);

async function main() {
    const commands = [
        new SlashCommandBuilder()
            .setName('play')
            .setDescription('Play a song')
            .addStringOption(option =>
                option.setName('query')
                      .setDescription('Search term or URL')
                      .setRequired(true)
            ),
        new SlashCommandBuilder()
            .setName('stop')
            .setDescription('Stop the music and clear the queue'),
        new SlashCommandBuilder()
            .setName('skip')
            .setDescription('Skip the current song'),
        new SlashCommandBuilder()
            .setName('queue')
            .setDescription('Show the current queue'),
        new SlashCommandBuilder()
            .setName('nowplaying')
            .setDescription('Show the currently playing song'),
        new SlashCommandBuilder()
            .setName('loop')
            .setDescription('Set the loop mode')
            .addStringOption(option =>
                option.setName('mode')
                      .setDescription('Loop mode')
                      .setRequired(true)
                      .addChoices(
                          { name: 'Off', value: 'off' },
                          { name: 'Track', value: 'track' },
                          { name: 'Queue', value: 'queue' }
                      )
            ),
        new SlashCommandBuilder()
            .setName('clearqueue')
            .setDescription('Clear all tracks from the queue'),
        new SlashCommandBuilder()
            .setName('volume')
            .setDescription('Set the player volume')
            .addIntegerOption(option =>
                option.setName('level')
                      .setDescription('Volume level (0-200)')
                      .setRequired(true)
                      .setMinValue(0)
                      .setMaxValue(200)
            ),
        new SlashCommandBuilder()
            .setName('bassboost')
            .setDescription('Toggle bass boost audio filter'),
        new SlashCommandBuilder()
            .setName('previous')
            .setDescription('Play the previous track'),
        new SlashCommandBuilder()
            .setName('lock-channel')
            .setDescription('Set a dedicated music control channel')
            .addChannelOption(option =>
                option.setName('channel')
                      .setDescription('The text channel for music controls')
                      .setRequired(true)
            ),
        new SlashCommandBuilder()
            .setName('unlock-channel')
            .setDescription('Remove the locked music channel (admin only)'),
        new SlashCommandBuilder()
            .setName('restart')
            .setDescription('Restart the bot (admin only)')
    ].map(cmd => cmd.toJSON());

    const rest = new REST({ version: '10' }).setToken(process.env.DISCORD_TOKEN);

    try {
        console.log('Registering commands globally...');
        await rest.put(
            Routes.applicationCommands('1448019272034156625'),  // Bot Application ID
            { body: commands }
        );
        console.log('Commands registered globally! They will appear in all servers within 1 hour (usually within 5-10 minutes).');
    } catch (error) {
        console.error(error);
    }
}

main();
