import discord
import asyncio
import datetime


client = discord.Client()

# Insert discord token here.
DISCORDTOKEN = None

# How many seconds before message gets deleted.
seconds = 3600

# Insert here the channels to link.
# Example: direct[123] = [124, 125]
# ^ This will copy entries from channel 123 and paste it in 124 and 125.
direct = dict()


async def get_webhook(channel):
	webhooks = await channel.webhooks()

	for webhook in webhooks:
		if webhook.name == 'Rift':
			return webhook
	
	return await channel.create_webhook(name = 'Rift')


@client.event
async def on_message(message):
	if message.author == client.user:
		print(message.webhook_id)
		return

	if message.webhook_id != None:
		# check our webhook before to delete message
		webhook = await get_webhook(message.channel)
		if webhook and webhook.id == message.webhook_id:
			await message.delete(delay=seconds)
		return

	if message.channel.id in direct:
		if message.author.nick == None: author = message.author.name
		else: author = message.author.nick

		content = "**" + author + "**: " + message.content

		for forward in direct[message.channel.id]:
			channel = client.get_channel(forward)
			webhook = await get_webhook(channel)

			await webhook.send(
				content = message.content,
				username = author,
				avatar_url = message.author.avatar_url,
				embeds = message.embeds
			)

			for attachment in message.attachments:
				await webhook.send(
					content = attachment.url,
					username = author,
					avatar_url = message.author.avatar_url,
				)


			# await channel.send(content, delete_after=seconds)

		await message.delete(delay=seconds)

		date = message.created_at.isoformat()
		backup = "[" + date + "] [" + message.guild.name + "] [" + message.channel.name + "] [" + author + "] " +  message.content + '\n'
		with open("backup.txt", "a+") as f: f.write(backup)



@client.event
async def on_ready():
	print('We have logged in as {0.user}'.format(client))
	for server in client.guilds:
		print("[" + str(server.id) + "] Server: " + server.name)



@client.event
async def on_disconnect():
	print('We have disconnected')


client.run(DISCORDTOKEN)
