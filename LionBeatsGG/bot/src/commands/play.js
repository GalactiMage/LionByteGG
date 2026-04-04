export default {
    name: 'play',
    description: 'Play music from YouTube/SoundCloud/Spotify',
    async execute(interaction) {
        const query = interaction.options.getString('query');
        const voice = interaction.member.voice.channel;

        if (!voice) return interaction.reply('🦁 Join a voice channel first.');

        const player = await interaction.client.music.createPlayer({
            guildId: interaction.guildId,
            voiceId: voice.id,
            textId: interaction.channelId,
            deaf: true
        });

        const result = await interaction.client.music.search(query, {
            requester: interaction.user
        });

        player.queue.add(result.tracks[0]);

        if (!player.playing) player.play();

        await interaction.reply(`🦁 Now playing: **${result.tracks[0].title}**`);
    }
};
