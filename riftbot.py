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
# Know which message is linked in direct.
# Example direct_message[871] = [<webhook obj 1>, <webhook obj 2>, <...>]
# ^ Those webhook messages will be affected by the original message
# ^ such as editing the message or deleting it
# Also it is used to track webhook message ids to original message id
# Example direct_message[233] = 112
# Also keep in mind that discord IDs are unique-ish, thus it must be safe
direct_message = dict()


async def get_webhook(channel):
	webhooks = await channel.webhooks()

	for webhook in webhooks:
		if webhook.name == 'Rift':
			return webhook

	return await channel.create_webhook(name = 'Rift')

def check_gif_url(content):
	return content.startswith('https://tenor.com/view/') or content.startswith('http://tenor.com/view/')

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

		# get files from message
		files = [await attach.to_file(spoiler = attach.is_spoiler()) for attach in message.attachments]

		# cache webhook message initialization
		webhook_message_dict = {
			'wait': True,
			'content': message.content,
			'username': author,
			'avatar_url': message.author.avatar_url,
			'embeds': [] if check_gif_url(message.content) else message.embeds,
			'files': files
		}

		for forward in direct[message.channel.id]:
			channel = client.get_channel(forward)
			webhook = await get_webhook(channel)

			webhook_message = await webhook.send(**webhook_message_dict)

			# possibly webhook message couldn't be sent
			if webhook_message:
				if message.id in direct_message:
					direct_message[message.id].append(webhook_message)
				else:
					direct_message[message.id] = [webhook_message]

				direct_message[webhook_message.id] = message.id

			# await channel.send(content, delete_after=seconds)

		await message.delete(delay=seconds)

		date = message.created_at.isoformat()
		backup = "[" + date + "] [" + message.guild.name + "] [" + message.channel.name + "] [" + author + "] " +  message.content + '\n'
		with open("backup.txt", "a+") as f: f.write(backup)

@client.event
async def on_message_edit(before, after):
	if after.webhook_id or not after.id in direct_message:
		return

	# update webhook content according to original message
	for webhook_message in direct_message[after.id]:
		await webhook_message.edit(
				content = after.content,
				embeds = [] if check_gif_url(after.content) else after.embeds
			)

@client.event
async def on_message_delete(message):
	# if original message is ever deleted, free memory
	if not message.id in direct_message:
		return

	value = direct_message[message.id]
	del direct_message[message.id]

	if message.webhook_id:
		webhook_messages = direct_message[value]
		for i, webhook_message in enumerate(webhook_messages):
			if webhook_message.id == message.id:
				del webhook_messages[i]
				break
	else:
		# delete webhook messages too
		for webhook_message in value:
			del direct_message[webhook_message.id]
			await webhook_message.delete()		

@client.event
async def on_ready():
	print('We have logged in as {0.user}'.format(client))
	for server in client.guilds:
		print("[" + str(server.id) + "] Server: " + server.name)

	# this is retrive a similar date to fetch previous message
	# as operation below might take some time
	#
	# Alert: time should be UTC due that discord date is in UTC
	#        otherwise this piece of code wouldn't work as expected
	actual_time = datetime.datetime.utcnow()

	for channel_id in direct:
		channel = client.get_channel(channel_id)

		# if that channel doesn't exist or bot is not 
		# in that guild anymore
		if not channel:
			continue

		async for message in channel.history(limit=None):
			# check how much time that message has left
			delay = seconds - (actual_time - message.created_at).total_seconds()
			await message.delete(delay=max(delay, 0))


@client.event
async def on_disconnect():
	print('We have disconnected')


client.run(DISCORDTOKEN)
