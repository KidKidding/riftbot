import discord
import asyncio
import datetime
import os
import json
import re


client = discord.Client()

# Insert discord token here.
DISCORDTOKEN = None

# How many seconds before message gets deleted.
seconds = 3600

# The direct_message cache file name
CACHE_MESSAGE_NAME = 'cm.dat'

# Gif URLs that Discord manually embed as gif
GIF_REGEX = r'https?://(?:tenor.com/view|c.tenor.com|giphy.com/gifs)/'

# Insert here the channels to link.
# Example: direct[123] = [124, 125]
# ^ This will copy entries from channel 123 and paste it in 124 and 125.
direct = dict()
# Know which message is linked in direct.
# Example direct_message[871] = [<webhook obj 1>, <webhook obj 2>, <...>, 123]
# ^ Those webhook messages will be affected by the original message
# ^ such as editing the message or deleting it
# Also it is used to track webhook message ids to original message id
# Example direct_message[233] = 112
# Also keep in mind that discord IDs are unique-ish, thus it must be safe
direct_message = dict()
# A tuple that contains two related data set, indicate below:
#  1.-A set to indicate that given message id will be loaded in direct_message
#  2.-A list of tasks to do [ function to run ], once that id has been
#     loaded in direct_message
lazy_direct_message = (set(), list())

# A wrapper about webhook messages, mainly it can be initialized as 
# webhook and given id or webhook message instead, in this way
# we can abstract in a layer to avoid that in other code places have to deal
# with this issue
class WebMessage:
	def __init__(self, *data):
		if len(data) == 2:
			self.__webhook = data[0]
			self.__id = data[1]
			self.__webhook_message = None
		elif len(data) == 1:
			self.__webhook_message = data[0]
		else:
			raise Exception(f'Invalid initialization {data}')

	def id(self):
		return self.__webhook_message.id if self.__webhook_message else self.__id

	async def edit(self, **fields):
		if self.__webhook_message:
			await self.__webhook_message.edit(**fields)
		else:
			await self.__webhook.edit_message(message_id = self.__id, **fields)

	async def delete(self, **fields):
		if self.__webhook_message:
			await self.__webhook_message.delete(**fields)
		else:
			if 'delay' in fields and fields['delay']:
				# discord.py API doesn't have a delay argument in delete
				# message, so to fix that issue, we can run a task using
				# asyncio API

				# dd stands by delayed delete
				async def dd():
					await asyncio.sleep(fields['delay'])
					await self.__webhook.delete_message(self.__id)	

				asyncio.ensure_future(dd())
			else:
				await self.__webhook.delete_message(self.__id)



async def get_webhook(channel):
	webhooks = await channel.webhooks()

	for webhook in webhooks:
		if webhook.name == 'Rift':
			return webhook

	return await channel.create_webhook(name = 'Rift')

def check_gif_url(content):
	return re.match(GIF_REGEX, content) is not None

async def _load_direct_message():
	# Restore cache messages from file
	if not os.path.isfile(CACHE_MESSAGE_NAME):
		return

	# filter channels that just are available
	channels = [channel for channel in [client.get_channel(id) for id in direct] if channel]
	# cache webhooks in all channels
	webhooks = dict()
	for channel in channels:
		webhook = await get_webhook(channel)
		webhooks[webhook.id] = webhook

	# return a dict of message ID linking to webhook ID if exists
	async def fetch_messages(ids: set):
		id_dict = dict()

		for channel in channels:
			async for message in channel.history(limit=None):
				if len(ids) == 0:
					break
				if not message.id in ids:
					continue

				id_dict[message.id] = message
				ids.remove(message.id)

		return id_dict

	with open(CACHE_MESSAGE_NAME, 'r') as file:
		data = json.load(file)

	lazy_direct_message[0].update([int(id) for id in data.keys()])

	# Fetch messages for better performance in large cached message list
	# this links IDs to messages, if message was deleted then it shouldn't
	# be in dict

	ids = set()
	for id, value in data.items():
		ids.update([int(id)] + value)

	cache_messages = await fetch_messages(ids)

	for id, value in data.items():
		# id in json was converted in string
		# so let's turn into int again
		id = int(id)

		# original message does not exist, so skip it
		if id not in cache_messages:
			continue

		# get a list of existing webhook messages related to this message
		# mdi means message id
		webhook_messages = [cache_messages[mid] for mid in value if mid in cache_messages]

		direct_message[id] = [
				WebMessage(webhooks[message.webhook_id], message.id)
				for message in webhook_messages
				if message.webhook_id in webhooks
			]

		# link webhook message ids with original message id again
		for webhook_message in webhook_messages:
			direct_message[webhook_message.id] = id

	lazy_direct_message[0].clear()
	for task in lazy_direct_message[1]:
		asyncio.ensure_future(task())
	lazy_direct_message[1].clear()


def _save_direct_message():
	# Save cache messages into file
	if len(direct_message) == 0:
		# if there is no data, delete file so

		if os.path.isfile(CACHE_MESSAGE_NAME):
			os.remove(CACHE_MESSAGE_NAME)

		return

	with open(CACHE_MESSAGE_NAME, 'w+') as file:
		data = dict()

		for id, value in direct_message.items():
			if not isinstance(value, list):
				continue

			# dump webhook messages into ids list
			data[id] = [webhook_message.id() for webhook_message in value]

		json.dump(data, file)


@client.event
async def on_message(message):
	if message.author == client.user or message.webhook_id:
		return

	if message.channel.id in direct:
		author = message.author.display_name

		#content = "**" + author + "**: " + message.content

		# get files from message
		raw_files = [(await attach.read(), attach) for attach in message.attachments]

		# cache webhook message initialization
		webhook_message_dict = {
			'wait': True,
			'content': message.content,
			'username': author,
			'avatar_url': message.author.avatar_url,
			'embeds': [] if check_gif_url(message.content) else message.embeds
		}

		for forward in direct[message.channel.id]:
			channel = client.get_channel(forward)
			webhook = await get_webhook(channel)

			files = [
				discord.File(
					fp = io.BytesIO(raw_file[0]),
					filename = raw_file[1].filename,
					spoiler = raw_file[1].is_spoiler()
				)
				for raw_file in raw_files
			]
			webhook_message = await webhook.send(**webhook_message_dict, files=files)

			# possibly webhook message couldn't be sent
			if webhook_message:
				if message.id in direct_message:
					direct_message[message.id].append(WebMessage(webhook_message))
				else:
					direct_message[message.id] = [WebMessage(webhook_message)]

				direct_message[webhook_message.id] = message.id

			# await channel.send(content, delete_after=seconds)

		await message.delete(delay=seconds)

		date = message.created_at.isoformat()
		backup = "[" + date + "] [" + message.guild.name + "] [" + message.channel.name + "] [" + author + "] " +  message.content + '\n'
		with open("backup.txt", "a+") as f: f.write(backup)

@client.event
async def on_message_edit(_ignored_, message):
	if message.webhook_id or not message.id in direct_message:
		if message.id in lazy_direct_message[0]:
			async def _fedit():
				await on_message_edit(None, message)

			lazy_direct_message[1].append(_fedit)

		return

	# update webhook content according to original message
	for webhook_message in direct_message[message.id]:
		await webhook_message.edit(
				content = message.content,
				embeds = [] if check_gif_url(message.content) else message.embeds
			)

# This event is to track messages that aren't in cached messages in bot
# then to keep monitoring and editing webhook messages with original message
# then we must be reading these raw messages edit too
@client.event
async def on_raw_message_edit(payload):
	# it's a cached message, so it was already processed
	# by on_message_edit(before, after)
	if payload.cached_message:
		return

	channel = await client.fetch_channel(payload.channel_id)
	message = await channel.fetch_message(payload.message_id)

	await on_message_edit(None, message)

@client.event
async def on_message_delete(message):
	# if original message is ever deleted, free memory
	if not message.id in direct_message:
		if message.id in lazy_direct_message[0]:
			async def _fdelete():
				await on_message_delete(message)

			lazy_direct_message[1].append(_fdelete)
		return

	value = direct_message[message.id]
	del direct_message[message.id]

	# int values indicate that is a webhook message linking to
	# a normal message
	if isinstance(value, int):
		webhook_messages = direct_message[value]
		for i, webhook_message in enumerate(webhook_messages):
			if webhook_message.id == message.id:
				del webhook_messages[i]
				break
	else:
		# delete webhook messages too
		for webhook_message in value:
			del direct_message[webhook_message.id()]
			await webhook_message.delete()

# This event is to track messages that aren't in cached messages in bot
# too, similar to on_raw_message_edit but now on raw message delete
@client.event
async def on_raw_message_delete(payload):
	# it's a cached message, so it was already processed
	# by on_message_delete(message)
	if payload.cached_message:
		return

	# a message prototype that just contains id attribute
	class _Message:
		def __init__(self, id):
			self.id = id


	await on_message_delete(_Message(payload.message_id))

@client.event
async def on_ready():
	print('We have logged in as {0.user}'.format(client))
	for server in client.guilds:
		print("[" + str(server.id) + "] Server: " + server.name)

	print('Loading cache message...')
	await _load_direct_message()

	print('Fetching messages to delete...')

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
			# we are just interest in original messages instead of
			# webhook messages, except if they are not linked
			if message.webhook_id and message.id in direct_message:
				continue

			# delete webhook messages instantly due that original message
			# wasn't found otherwise these webhook messages would in
			# direct_message too
			if message.webhook_id:
				await message.delete()
			else:
				# check how much time that message has left
				delay = seconds - (actual_time - message.created_at).total_seconds()
				await message.delete(delay=max(delay, 0))

	print('Done!')


@client.event
async def on_disconnect():
	print('We have disconnected')

	# if bot goes offline either by own connection or discord stuff
	# we should save direct messages due that when be ready again
	# it'd be reading the previous file with old data
	_save_direct_message()

client.run(DISCORDTOKEN)

# save finally direct_message because on_disconnection won't be called
# when we turn the bot off
_save_direct_message()
