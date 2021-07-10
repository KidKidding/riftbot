import discord
import asyncio
import datetime
import os
import json
import re
import io
import sys


client = discord.Client()

# Insert discord token here.
DISCORDTOKEN = None

# How many seconds before message gets deleted.
seconds = 3600

# The direct_message cache file name
CACHE_MESSAGE_NAME = 'cm.dat'

# Indexes used in cache message file to indicate some info
ID_MESSAGE_IDX = 0
REPLY_MESSAGE_IDX = 1

# Gif URLs that Discord manually embed as gif
GIF_REGEX = r'https?://(?:tenor.com/view|c.tenor.com|giphy.com/gifs)/'

# this will match for:
# - <@USER_ID>
# - <@!USER_ID>
# - <#CHANNEL_ID>
# - <@&ROLE_ID>
# - <:NAME:ID>
# - <a:NAME:ID>
MESSAGE_FORMAT_REGEX = r'<(@!?&?|#|a?:[A-Za-z0-9_~]+:)\d+>'

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
	NO_REPLY = 0

	# reply -> message id to reference, NO_REPLY if there is no
	def __init__(self, *data, reply=NO_REPLY):
		self.reply = reply

		if len(data) == 2:
			self.__webhook = data[0]
			self.__id = data[1]
			self.__webhook_message = None
			self.__message = None
		elif len(data) == 1:
			self.__webhook_message = data[0]
			self.__message = data[0]
		else:
			raise Exception(f'Invalid initialization {data}')

	def id(self):
		return self.__webhook_message.id if self.__webhook_message else self.__id

	# return channel that is this message
	def channel(self):
		return self.__webhook_message.channel if self.__webhook_message else self.__webhook.channel

	# resolve message or None if it couldn't be found
	async def message(self):
		if self.__message is not None:
			return self.__message

		try:
			self.__message = await self.__webhook.channel.fetch_message(self.__id)
			return self.__message
		except discord.errors.NotFound:
			return None

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

def get_reply_direct(id):
	value = direct_message.get(id)
	if value is None or not isinstance(value, int):
		return None

	message_list = direct_message[value]
	for message in message_list:
		if message.id() == id:
			return message if message.reply != WebMessage.NO_REPLY else None

	return None

def short_reply_content(content):
	expected_size = 60

	# make linear message instead
	content = content.replace('\n', ' ')

	# increase expected size if some message format is found
	# such as pings, emojis, etc
	#
	# for instance, emojis will be use 1 space
	for match in re.finditer(MESSAGE_FORMAT_REGEX, content):
		# add the length of match
		expected_size += match.end() - match.start()

	size = len(content)
	short = content[0 : min(size, expected_size)]

	# add "..." at the end if message is large
	# than expected characters
	return short + '...' if size > expected_size else short

def process_emojis(text, guild):
	'''
	Replaces the emojis of the form :name: in the string text with emojis of the form <:name:\d{18}> or <a:name:\d{18}>.
	Note: Only works for emojis with 18-digit IDs since I thought that emojis can only have 18-digit IDs :sadcat:
	'''
	for name, emoji in ((f':{x.name}:', str(x)) for x in guild.emojis):
		start_index = 0
		name_index = text.find(name, start_index)
		while name_index != -1:
			if (
				re.fullmatch(
					'<' + name + r'\d{18}>',
					text[name_index - 1:name_index + len(name) + 19]) or
				re.fullmatch(
					'<a' + name + r'\d{18}>',
					text[name_index - 2:name_index + len(name) + 19])
			):
				start_index = name_index + len(name) + 19
			else:
				text = text[:name_index] + text[name_index:].replace(name, emoji, 1)
				start_index = name_index + len(emoji)
			name_index = text.find(name, start_index)

	return text

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
		if not isinstance(value, list):
			continue

		ids.update([int(id)] + [metadata[ID_MESSAGE_IDX] for metadata in value])

	cache_messages = await fetch_messages(ids)

	for id, value in data.items():
		if not isinstance(value, list):
			continue

		# id in json was converted in string
		# so let's turn into int again
		id = int(id)

		# original message does not exist, so skip it
		if id not in cache_messages:
			continue

		id_list = list()
		reply_meta = dict()

		for metadata in value:
			id_list.append(metadata[ID_MESSAGE_IDX])
			reply_meta[metadata[ID_MESSAGE_IDX]] = metadata[REPLY_MESSAGE_IDX]

		# get a list of existing webhook messages related to this message
		# mdi means message id
		webhook_messages = [cache_messages[mid] for mid in id_list if mid in cache_messages]

		direct_message[id] = [
			WebMessage(webhooks[message.webhook_id], message.id, reply=reply_meta[message.id])
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

			# dump webhook messages into metadata [ IDs, replies ]
			#
			# alert: these should be ordered as indexes values above
			data[id] = [[webhook_message.id(), webhook_message.reply] for webhook_message in value]

		json.dump(data, file)


@client.event
async def on_message(message):
	if message.author == client.user or message.webhook_id:
		return

	if message.channel.id in direct:
		def get_author_name(author):
			author_name = author.name

			if author.discriminator != '0000':
				author_name = f'{author_name}#{author.discriminator}'

			try:
				author_name = f'{author.nick} ({author})'
			except:
				# possibly nick attribute doesn't even exist
				pass

			return author_name

		author = get_author_name(message.author)
		avatar_url = message.author.avatar_url

		# get files from message
		raw_files = [(await attach.read(), attach) for attach in message.attachments]

		# cache webhook message initialization
		webhook_message_dict = {
			'wait': True,
			'content': process_emojis(message.content, message.guild),
			'username': author,
			'avatar_url': avatar_url,
			'embeds': [] if check_gif_url(message.content) else message.embeds,
			'allowed_mentions': discord.AllowedMentions(everyone=False, roles=False)
		}

		reference = message.reference
		webhook_reply_dict = None

		if reference is not None:
			reference_message = reference.cached_message
			if reference_message is None:
				reference_channel = client.get_channel(reference.channel_id)
				try:
					reference_message = await reference_channel.fetch_message(reference.message_id)
				except discord.errors.NotFound:
					# it could be deleted just in time when message was sent
					reference_message = None

			if reference_message is not None:
				rcontent = reference_message.content

				# check if reference is reply, to avoid applying reply format again
				# otherwise apply it

				web_reply = get_reply_direct(reference.message_id)
				if web_reply is None:
					rcontent = f'> **{get_author_name(reference_message.author)}**: {short_reply_content(rcontent)}'

				webhook_reply_dict = {
					'wait': True,
					'content': rcontent,
					'username': author,
					'avatar_url': avatar_url,
					'allowed_mentions': discord.AllowedMentions.none()
				}

		for forward in direct[message.channel.id]:
			channel = client.get_channel(forward)
			webhook = await get_webhook(channel)

			# initialize webhook message reply as None
			webhook_message_reply = None

			# send webhook message reply before than user message
			if webhook_reply_dict is not None:
				webhook_message_reply = await webhook.send(**webhook_reply_dict)

				# webhook message reply couldn't be sent
				if webhook_message_reply is not None:
					# the point of this is to link another webhook message
					# into list of some message JUST if that message is being
					# tracked in direct_message otherwise don't append and
					# insert a new list

					web_message_reply = WebMessage(webhook_message_reply, reply=reference.message_id)

					if reference.message_id in direct_message:
						reference_message_id = reference.message_id

						direct_value = direct_message[reference_message_id]
						if isinstance(direct_value, int):
							reference_message_id = direct_value
							direct_value = direct_message[reference_message_id]

						direct_value.append(web_message_reply)
						direct_message[webhook_message_reply.id] = reference_message_id

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
			if webhook_message is not None:
				direct_message.setdefault(message.id, list()).append(WebMessage(webhook_message))

				# append webhook message reply to that message
				# because message created that reply
				if webhook_message_reply is not None:
					direct_message[message.id].append(web_message_reply)

				# assign which is original message id in webhook message
				direct_message[webhook_message.id] = message.id

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
		if webhook_message.reply != WebMessage.NO_REPLY:
			# check if reply id is the message id that is being
			# editted, otherwise it is the message that replied
			# the other one
			if webhook_message.reply != message.id:
				return

			# short the new content
			short_content = short_reply_content(message.content)

			# recover user mention to message that was replied
			# because reply format is `> {mention}: {message}`
			# so we'd be finding the first : in that format
			# but if message couldn't be found, show `*error*` instead

			resolved_webhook_message = await webhook_message.message()
			if resolved_webhook_message is not None:
				resolved_content = resolved_webhook_message.content
				content = f"{resolved_content[0:resolved_content.find(':')]}: {short_content}"
			else:
				content = f'> *error*: {short_content}'

			await webhook_message.edit(
				content = process_emojis(content, message.guild),
				allowed_mentions = discord.AllowedMentions.none()
			)
		else:
			await webhook_message.edit(
				content = process_emojis(message.content, message.guild),
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
		webhook_messages = direct_message.get(value, list())
		for i, webhook_message in enumerate(webhook_messages):
			if webhook_message.id == message.id:
				del webhook_messages[i]
				break
	else:
		# delete webhook messages too
		for webhook_message in value:
			direct_message.pop(webhook_message.id(), None)

			try:
				await webhook_message.delete()
			except discord.errors.NotFound:
				# it could be a reply, therefore it may be removed before
				pass

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

if os.path.isfile(CACHE_MESSAGE_NAME):
	# Check json before to run bot
	with open(CACHE_MESSAGE_NAME, 'r') as file:
		try:
			data = json.load(file)
		except json.decoder.JSONDecodeError as error:
			# json is bad formatted
			# possibly it didn't save correctly or it was
			# editted by someone that forgot some things
			print(f'Error while loading {CACHE_MESSAGE_NAME} file: {error}', file=sys.stderr)
			# Exit to avoid that file override or delete itself
			exit(0)

client.run(DISCORDTOKEN)

# save finally direct_message because on_disconnection won't be called
# when we turn the bot off
_save_direct_message()
