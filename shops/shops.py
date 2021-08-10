import logging
import asyncio
import time
from datetime import datetime

import discord
from typing import List

from redbot.core import Config, commands
from redbot.core.utils.menus import menu, DEFAULT_CONTROLS
from redbot.core.utils.chat_formatting import box, humanize_number
from redbot.core.utils.menus import start_adding_reactions
from tabulate import tabulate

logger = logging.getLogger("red.RedX.Shops")


class Shops(commands.Cog):
    """Système de boutiques personnalisées"""

    def __init__(self, bot):
        super().__init__()
        self.bot = bot
        self.config = Config.get_conf(self, identifier=736144321857978388, force_registration=True)

        default_member = {'Shop': {},
                          'ManualIDs': {}}

        default_guild = {'GlobalLogs': {}}
        
        self.config.register_member(**default_member)
        self.config.register_guild(**default_guild)
        
    async def check_key_validity(self, guild: discord.Guild, key: str):
        all_members = await self.config.all_members(guild)
        all_shops = [all_members[u]['Shop'] for u in all_members]
        all_keys = [i for s in all_shops for i in s]
        return not (key in all_keys)
    
    async def is_shop_item(self, guild: discord.Guild, itemid: str):
        all_members = await self.config.all_members(guild)
        for m in all_members:
            for i in all_members[m]['Shop']:
                if i == itemid:
                    return True
        return False
    
    async def get_shop_item(self, guild: discord.Guild, itemid: str):
        all_members = await self.config.all_members(guild)
        for m in all_members:
            for i in all_members[m]['Shop']:
                if i == itemid:
                    return guild.get_member(m), all_members[m]['Shop'][i]
        return None, None
    
    async def clear_manualids(self, member: discord.Member):
        ids = await self.config.member(member).ManualIDs()
        for i in ids:
            if ids[i]['timestamp'] + 86400 < time.time():
                await self.config.member(member).ManualIDs.clear_raw(i)
    
    async def log_shop_operation(self, buyer: discord.Member, seller: discord.Member, itemid: str, qte: int, **info):
        """Log une opération de vente"""
        uid = str(int(time.time() * 100))
        log = {'buyer': buyer.id, 'seller': seller.id, 'item': itemid, 'qte': qte, 'timestamp': time.time()}
        log.update(info)
        
        await self.config.guild(buyer.guild).GlobalLogs.set_raw(uid, value=log)
        return uid
    
    async def log_contract(self, guild: discord.Guild, members: List[discord.Member], content: str, expiration_date: float, credits: int = None, **info):
        """Log un contrat manuel"""
        uid = str(int(time.time() * 100))
        log = {'members': [m.id for m in members], 'content': content, 'expiration_date': expiration_date, 'credits': credits, 'timestamp': time.time()}
        log.update(info)
        
        await self.config.guild(guild).GlobalLogs.set_raw(uid, value=log)
        return uid
    
    async def clear_expired_contracts(self, guild: discord.Guild):
        logs = await self.config.guild(guild).GlobalLogs()
        for l in logs:
            if 'expiration_date' in logs[l]:
                if logs[l]['expiration_date'] > time.time():
                    await self.config.guild(guild).GlobalLogs.clear_raw(l)

    async def get_log_ticket(self, guild: discord.Guild, logid: str) -> discord.Embed:
        logs = await self.config.guild(guild).GlobalLogs()
        if logid in logs:
            log = logs[logid]
            buyer = guild.get_member(log['buyer'])
            seller, item = await self.get_shop_item(guild, log['item'])
            ticket = discord.Embed(title=f"**Preuve d'achat** · `${logid}`", color=buyer.color if buyer else None,
                                   timestamp=datetime.utcfromtimestamp(log['timestamp']))
            ticket.description = f"Vente réalisée entre {seller.name if seller else '???'} (Vendeur) et {buyer.name if buyer else '???'} (Acheteur)"
            if item:
                ticket.add_field(name="Item concerné", value=f"**{item['name']}** (`{log['item']}`)")
                if item.get('img', False):
                    ticket.set_thumbnail(url=item['img'])
            else:
                ticket.add_field(name="Item concerné", value=f"Anciennement `{log['item']}`")
            ticket.add_field(name="Quantité", value=box('x' + str(log['qte'])))
            return ticket
        return None
    
    async def get_contract_info(self, guild: discord.Guild, con_id: str):
        await self.clear_expired_contracts(guild)
        logs = await self.config.guild(guild).GlobalLogs()
        if con_id in logs:
            log = logs[con_id]
            members = [guild.get_member(m) for m in log['members']]
            
            em = discord.Embed(title=f"**Contrat** · `${con_id}`", color=discord.Color.dark_grey(), timestamp=datetime.utcfromtimestamp(log['timestamp']))['']
            em.description = f"{log['content']}"
            em.add_field(name="Membres concernés", value="\n".join((f"{members.index(m) + 1}. {m.mention}" for m in members)))
            if log.get('credits', None):
                em.add_field(name="Somme concernée", value=box(log['credits'], lang='css'))
            date = datetime.now().fromtimestamp(log['expiration_date']).strftime('%d/%m/%Y')
            em.add_field(name="Expire le", value=box(date))
            em.set_footer(name=f"Garanti par {self.bot.user.name}")
            return em
        return None


    @commands.group(name='shop', invoke_without_command=True)
    @commands.guild_only()
    async def member_shop_commands(self, ctx, user: discord.Member = None):
        """Voir et gérer sa boutique personnelle"""
        if ctx.invoked_subcommand is None:
            return await ctx.invoke(self.get_user_shop, user=user)
        
    @member_shop_commands.command(name='show')
    async def get_user_shop(self, ctx, user: discord.Member = None):
        """Affiche une représentation de la boutique du membre visé
        
        Affiche sa propre boutique s'il y a aucune mention"""
        user = user if user else ctx.author
        shop = await self.config.member(user).Shop()
        
        n = 1
        embeds = []
        for itemid in shop:
            item = shop[itemid]
            em = discord.Embed(title=f"`{itemid}` › **{item['name']}**", 
                               description=f"*{item.get('description', 'Aucune description')}*",
                               color=user.color)
            
            if item.get('img', None):
                em.set_thumbnail(url=item['img'])
            
            if 'qte' in item:
                em.add_field(name="Quantité disp.", value=box(item['qte'], lang='css'))
                
            em.add_field(name="Prix à l'unité", value=box(item['value'], lang='fix'))
            em.add_field(name="Type de vente", value=box(f"{'Manuelle' if item['sellmode'] == 'manual' else 'Automatisée'}"))
            
            em.set_footer(text=f"Item {n}/{len(shop)} · {user.name}")
            n += 1
            embeds.append(em)
            
        if embeds:
            await menu(ctx, embeds, DEFAULT_CONTROLS)
        else:
            return await ctx.reply(f"**Boutique vide** • *{user.name}* n'a aucun élément à proposer", mention_author=False)
        
    @member_shop_commands.command(name='buy')
    @commands.cooldown(1, 20, commands.BucketType.member)
    async def buy_shop_item(self, ctx, itemid: str, qte: int = 1):
        """Acheter X item d'une boutique avec son identifiant
        
        Si aucune quantité n'est précisée, vous en acheterez un seul"""
        seller, item = await self.get_shop_item(ctx.guild, itemid)
        eco = self.bot.get_cog('AltEco')
        curr = await eco.get_currency(ctx.guild)
        
        if not seller:
            return await ctx.reply(f"**Identifiant d'item inconnu** • Vérifiez l'identifiant dans la boutique du membre puis réessayez", mention_author=False)
        
        if 'qte' in item:
            if qte > item['qte']:
                return await ctx.reply(f"**Quantité trop importante** • La boutique visée n'a pas cette quantité d'items à disposition, consultez `;shop {seller.name}` pour en savoir plus.", mention_author=False)
        
        em = discord.Embed(title=f"`{itemid}` › **{item['name']}**", 
                            description=f"*{item.get('description', 'Aucune description')}*",
                            color=seller.color)
        if item.get('img', None):
            em.set_thumbnail(url=item['img'])
        if 'qte' in item:
            em.add_field(name="Quantité disp.", value=box(item['qte'], lang='css'))
        
        em.add_field(name="Prix à l'unité", value=box(item['value'], lang='fix'))
        em.add_field(name="Type de vente", value=box(f"{'Manuelle' if item['sellmode'] == 'manual' else 'Automatisée'}"))
        em.set_footer(text=f"Boutique de {seller.name}\n››› Confirmer l'achat de x{qte} {itemid} ?")
        msg = await ctx.reply(embed=em, mention_author=False)
        start_adding_reactions(msg, ['✅', '❎'])
        try:
            react, _ = await self.bot.wait_for("reaction_add",
                                                check=lambda m,
                                                            u: u == ctx.author and m.message.id == msg.id,
                                                timeout=30)
        except asyncio.TimeoutError:
            await ctx.reply("Achat annulé.", mention_author=False)
            return await msg.delete()
        
        if react.emoji == '❎':
            await ctx.reply("Achat annulé.", mention_author=False)
            return await msg.delete()
        
        await msg.delete()
        sellmode = item['sellmode']
        if sellmode == 'manual':
            buyid = str(int(time.time() * 10))
            manualdata = {'item': itemid, 'qte': qte, 'buyer': ctx.author.id, 'timestamp': time.time()}
            await self.config.member(seller).ManualIDs.set_raw(buyid, value=manualdata)
            
            sellem = discord.Embed(title=f"Demande d'achat · `{itemid}` **{item['name']}**", description=f"**{ctx.author}** sur *{ctx.guild.name}* désire acheter l'item **x{qte}** `{itemid}`.", color=seller.color)
            if 'qte' in item:
                sellem.add_field(name="Quantité disp.", value=box(item['qte'], lang='css'))
            sellem.add_field(name="Identifiant d'achat", value=box(buyid, lang='fix'))
            sellem.set_footer(text=f"Acceptez la vente en faisant ';shop sell <id>' dans les 24h sur le serveur ou ignorez-la pour refuser")
            try:
                await seller.send(embed=sellem)
            except:
                await ctx.send(f'{seller.mention}', embed=sellem)
            
            await ctx.reply(f"**Demande d'achat envoyée** • Le vendeur doit accepter dans les 24h avec `;shop sell {buyid}`, sinon votre achat sera automatiquement refusé. Si le vendeur retire l'item de la boutique ou vend la quantité à un autre membre, l'achat sera aussi annulé.")
        else:
            if not await eco.check_balance(ctx.author, item['value'] * qte):
                return await ctx.reply(f"**Fonds insuffisants** • Cet achat vous coûte {item['value'] * qte}{curr} mais vous n'avez que {await eco.get_balance(ctx.author)}{curr}.")
            
            uid = await self.log_shop_operation(ctx.author, seller, itemid, qte)
            await eco.withdraw_credits(ctx.author, item['value'] * qte, desc=f"Achat boutique ${uid}")
            await eco.deposit_credits(seller, item['value'] * qte, desc=f"Vente boutique ${uid}")
            
            if 'qte' in item:
                await self.config.member(seller).Shop.set_raw(itemid, 'qte', value=item['qte'] - qte)
            
            return await ctx.reply(f"**Achat effectué** • Vous avez acheté x{qte} **{item['name']}** à {seller.mention} pour {qte * item['value']}{curr}.", embed=await self.get_log_ticket(ctx.guild, uid))
            
    @member_shop_commands.command(name='sell')
    async def sell_shop_item(self, ctx, opeid: str = None):
        """Accepter la vente d'un item manuellement (les numéros d'opération sont représentés avec un $ devant)
        
        Cette acceptation doit être faite dans les 24h après la demande, sans quoi l'opération est automatiquement annulée
        Ne pas mettre d'ID d'opération vous affiche celles qui sont en attente"""
        author = ctx.author
        await self.clear_manualids(author)
        ids = await self.config.member(author).ManualIDs()
        eco = self.bot.get_cog('AltEco')
        curr = await eco.get_currency(ctx.guild)
        if not opeid:
            if not ids:
                return await ctx.reply(f"**Aucune opération en attente** • Vous n'avez pas de vente en attente d'être réalisée", mention_author=False)
            em = discord.Embed(title="Opérations en attente", description=box("\n".join([f"{o} · {ids[o]['item']} x{ids[o]['qte']} par {ctx.guild.get_member(ids[o]['buyer'])}" for o in ids])))
            return await ctx.reply(embed=em, mention_author=False)
            
        if opeid in ids:
            data = ids[opeid]
            itemid = data['item']
            buyer = ctx.guild.get_member(data['buyer'])
            if not buyer:
                return await ctx.reply(f"**Opération invalide** • L'acheteur ne se trouve plus sur ce serveur", mention_author=False)
            
            _, item = await self.get_shop_item(ctx.guild, itemid)
            if item:
                if 'qte' in item:
                    if data['qte'] > item['qte']:
                        return await ctx.reply(f"**Quantité trop importante** • Votre boutique n'a plus la quantité commandée d'items à disposition, l'opération est donc suspendue.", mention_author=False)
                    
                sellem = discord.Embed(title=f"Demande d'achat · `{itemid}` › **{item['name']}**", description=f"**{ctx.author}** sur *{ctx.guild.name}* désire acheter l'item **x{data['qte']}** `{itemid}`.", color=author.color)
                if 'qte' in item:
                    sellem.add_field(name="Quantité disp.", value=box(item['qte'], lang='css'))
                sellem.add_field(name="Expiration", value=box(datetime.utcfromtimestamp(data['timestamp']).strftime('%d/%m/%Y %H:%M')))
                sellem.set_footer(text=f"››› Acceptez-vous cette vente ? [Silence vaut suspension] (60s)")
                msg = await ctx.reply(embed=sellem, mention_author=False)
                start_adding_reactions(msg, ['✅', '❎'])
                try:
                    react, _ = await self.bot.wait_for("reaction_add",
                                                        check=lambda m,
                                                                    u: u == ctx.author and m.message.id == msg.id,
                                                        timeout=60)
                except asyncio.TimeoutError:
                    await ctx.reply("Opération suspendue, vous pourrez refaire la commande pour cette opération tant qu'elle n'a pas expiré.", mention_author=False)
                    return await msg.delete()
                
                if react.emoji == '❎':
                    await ctx.reply("Opération refusée.", mention_author=False)
                    await self.config.member(ctx.author).ManualIDs.clear_raw(opeid)
                    return await msg.delete()
                
                else:
                    if not await eco.check_balance(buyer, item['value'] * data['qte']):
                        return await ctx.send(f"{buyer.mention} **Fonds insuffisants** • Cet achat vous coûte {item['value'] * data['qte']}{curr} mais vous n'avez que {await eco.get_balance(ctx.author)}{curr}.")
                    
                    await msg.delete()
                    await self.config.member(ctx.author).ManualIDs.clear_raw(opeid)
                    uid = await self.log_shop_operation(buyer, ctx.author, itemid, data['qte'])
                    await eco.withdraw_credits(buyer, item['value'] * data['qte'], desc=f"Achat boutique ${uid}")
                    await eco.deposit_credits(ctx.author, item['value'] * data['qte'], desc=f"Vente boutique ${uid}")
                    
                    if 'qte' in item:
                        await self.config.member(ctx.author).Shop.set_raw(itemid, 'qte', value=item['qte'] - data['qte'])
                    
                    return await ctx.reply(f"**Vente effectuée** • Vous avez vendu x{data['qte']} **{item['name']}** à {buyer.mention} pour {data['qte'] * item['value']}{curr}.", embed=await self.get_log_ticket(ctx.guild, uid))
            else:
                return await ctx.reply(f"**Opération impossible** • L'item commandé par le membre n'est plus disponible dans votre boutique", mention_author=False)
        return await ctx.reply(f"**Opération inconnue** • Cet identifiant n'existe pas. Ne mettez pas le symbole $ (dollar) avant l'identifiant.", mention_author=False)

    
    @member_shop_commands.command(name='new')
    async def new_shop_item(self, ctx):
        """Ajouter un nouvel item dans sa boutique"""
        author = ctx.author
        shop = await self.config.member(author).Shop()
        eco = self.bot.get_cog('AltEco')
        curr = await eco.get_currency(ctx.guild)
        
        if len(shop) >= 5:
            return await ctx.reply(f"**Ajout d'item impossible** • Votre boutique ne peut contenir que 5 items différents, libérez d'abord de la place avec `;shop rem`")
        
        await ctx.reply(f"**Processus d'ajout d'item** • Vous allez être guidé à travers les différentes étapes d'ajout d'un item à votre boutique. En cas d'erreur, vous devrez refaire la commande et refaire chaque étape.\nVous pouvez dire 'stop' à tout moment pour arrêter.", mention_author=False)
        await asyncio.sleep(3)
        
        async def query_value(desc: str, timeout_delay: int = 30):
            qem = discord.Embed(description=desc, color = author.color)
            qem.set_footer(text=f"››› Entrez l'élement ci-dessous ({timeout_delay}s)")
            await ctx.send(embed=qem)
            try:
                resp = await self.bot.wait_for('message',
                                               timeout=timeout_delay,
                                               check=lambda m: m.author == ctx.author and m.channel == ctx.channel)
            except asyncio.TimeoutError:
                return None
            if resp.content.lower() in ('stop', 'annuler', 'quitter', 'aucun', 'aucune', 'rien'):
                return None
            return resp.content
        
        itemid = await query_value("**A. Identifiant d'item :** C'est l'identifiant unique qui va permettre aux membres d'acheter votre item.\nCelui-ci ne peut pas contenir d'espaces ou de caractères spéciaux (y compris accents) et doit faire 20 caractères max.")
        if not itemid:
            return await ctx.send("Ajout d'item annulé")
        elif await self.is_shop_item(ctx.guild, itemid):
            return await ctx.send("**Identifiant déjà utilisé** • Cet identifiant existe déjà pour un autre item sur ce serveur")
        elif ' ' in itemid:
            return await ctx.send("**Identifiant invalide** • L'identifiant ne peut contenir un espace")
        elif len(itemid) > 20:
            return await ctx.send("**Identifiant invalide** • L'identifiant ne peut faire plus de 20 caractères")
        await asyncio.sleep(0.5)
        
        name = await query_value("**B. Nom de l'item :** C'est le nom qui s'affichera dans la boutique pour cet item.\nIl ne doit pas faire plus de 50 caractères.", 60)
        if not name:
            return await ctx.send("Ajout d'item annulé")
        elif len(name) > 50:
            return await ctx.send("**Nom invalide** • Le nom ne peut faire plus de 50 caractères")
        await asyncio.sleep(0.5)
        
        desc = await query_value("**C. Description :** Une rapide description de l'item ou du service vendu.\nElle ne peut pas faire plus de 400 caractères et le markdown est supporté (y compris l'intégration de liens).", 300)
        if not desc:
            return await ctx.send("Ajout d'item annulé")
        elif len(desc) > 400:
            return await ctx.send("**Description invalide** • La description ne peut faire plus de 400 caractères")
        await asyncio.sleep(0.5)
        
        qte = await query_value("**D. Quantité :** Nombre d'exemplaires disponibles de cet item, s'il est dénombrable.\nLa quantité doit être positive s'il y en a une. Mettre '0' indiquera que l'item peut être vendu à l'infini (jusqu'au retrait manuel)", 60)
        if not qte:
            return await ctx.send("Ajout d'item annulé")
        try:
            qte = int(qte)
            if qte < 0:
                return await ctx.send("**Quantité invalide** • Le nombre est invalide car négatif")
        except:
            return await ctx.send("**Quantité invalide** • Nombre introuvable dans votre réponse")
        await asyncio.sleep(0.5)
        
        mem = discord.Embed(description="**E. Mode de vente :** Mode de fonctionnement de la vente pour cet item parmi les deux modes disponibles\n`A` = La vente se fait automatiquement dès que le membre fait la commande d'achat\n`B` = Vous devez confirmer manuellement chaque vente avec `;shop sell`\n\nLe deuxième mode est utile pour se servir de la boutique comme hub de commandes.",
                            color=author.color)
        mem.set_footer(text="››› Choisissez le mode désiré pour cet item en cliquant sur la réaction correspondante")
        msg = await ctx.send(embed=mem)
        start_adding_reactions(msg, ['🇦', '🇧'])
        try:
            react, _ = await self.bot.wait_for("reaction_add",
                                                    check=lambda m,
                                                                u: u == ctx.author and m.message.id == msg.id,
                                                    timeout=45)
        except asyncio.TimeoutError:
            await ctx.send("Ajout d'item annulé")
            return await msg.delete()

        if react.emoji == '🇦':
            sellmode = 'auto'
        else:
            sellmode = 'manual'
                
        await asyncio.sleep(0.5)
        
        value = await query_value("**F. Prix :** Prix de l'item à l'unité.\nLe prix doit être un nombre positif ou nul (si gratuit).")
        if not value:
            return await ctx.send("Ajout d'item annulé")
        try:
            value = int(value)
            if qte < 0:
                return await ctx.send("**Prix invalide** • Le nombre est invalide car négatif")
        except:
            return await ctx.send("**Prix invalide** • Nombre introuvable dans votre réponse")
        await asyncio.sleep(0.5)
        
        img = await query_value("**G. Image de représentation (Optionnel) :** URL d'une image représentant l'item que vous vendez.\nPour ne rien mettre, répondez 'rien' ou 'aucune'.", 120)
        if not img:
            img = False
        await asyncio.sleep(0.5)
        
        resume = f"**__Nom :__** {name}\n**__Description :__** {desc if len(desc) < 50 else desc[:50] + '...'}\n**__Quantité vendue :__** {qte if qte > 0 else 'Indefinie'}\n**__Mode de vente :__** {sellmode.title()}\n**__Prix à l'unité :__** {value}{curr}/u\n**__URL de l'image :__** {img if img else 'Aucune'}"
        em = discord.Embed(title=f"Résumé › `{itemid}`",
                           description=resume,
                           color=author.color)
        em.set_footer(text="››› Confirmez-vous ces données ? [Silence vaut confirmation]")
        msg = await ctx.send(embed=em)
        start_adding_reactions(msg, ['✅', '❎'])
        try:
            react, _ = await self.bot.wait_for("reaction_add",
                                                    check=lambda m,
                                                                u: u == ctx.author and m.message.id == msg.id,
                                                    timeout=60)
        except asyncio.TimeoutError:
            pass
        
        if react.emoji == '❎':
            await ctx.send("Ajout de l'item annulé, refaire la commande pour changer les données")
            return await msg.delete()
        
        itemdata = {'name': name, 'description': desc, 'value': value, 'sellmode': sellmode}
        if qte:
            itemdata['qte'] = qte
        if img:
            itemdata['img'] = img

        await self.config.member(author).Shop.set_raw(itemid, value=itemdata)
        if sellmode is 'auto':
            await ctx.send(f"✅ **Succès** • L'item `{itemid}` a été ajouté dans votre boutique !")
        else:
            await ctx.send(f"✅ **Succès** • L'item `{itemid}` a été ajouté dans votre boutique !\n__Rappel :__ Le mode de vente étant en 'Manuel', vous recevrez des MP de vente lorsque quelqu'un voudra acheter un item et vous devrez confirmer la vente avec la commande `;shop sell`. **Vérifiez donc que le bot puisse avoir accès à vos MP.**")
        
    @member_shop_commands.command(name='add')
    async def add_shop_item(self, ctx, itemid: str, qte: int):
        """Ajouter une quantité d'un item de sa boutique"""
        user = ctx.author
        shop = await self.config.member(user).Shop()
        if qte < 0:
            return await ctx.reply(f"**Quantité invalide** • Vous ne pouvez pas ajouter une quantité négative d'items", mention_author=False)
        if itemid not in shop:
            return await ctx.reply(f"**Item invalide** • Cet item n'existe pas dans votre boutique. Si vous voulez ajouter un nouvel item, utilisez `;shop new`", mention_author=False)
        
        item = shop[itemid]
        if 'qte' not in item:
            return await ctx.reply(f"**Action impossible** • Cet item n'est pas dénombrable. Si vous voulez qu'il soit quantifié, vous devez l'effacer avec `;shop remove` et le refaire avec `;shop new`", mention_author=False)
        
        await self.config.member(user).Shop.set_raw(itemid, 'qte', value=item['qte'] + qte)
        await ctx.reply(f"**Ajout effectué** • L'item `{itemid}` est désormais disponible en x{item['qte'] + qte} exemplaires", mention_author=False)    
    
    @member_shop_commands.command(name='remove', aliases=['rem'])
    async def remove_shop_item(self, ctx, itemid: str, qte: int = None):
        """Retirer un item de sa boutique par son identifiant
        
        Préciser [qte] permet de retirer une certaine quantité de l'item si celui-ci est dénombrable"""
        user = ctx.author
        shop = await self.config.member(user).Shop()
        await self.clear_manualids(user)
        manualids = await self.config.member(user).ManualIDs()
        
        if itemid not in shop:
            return await ctx.reply(f"**Identifiant d'item inconnu** • Vérifiez les identifiants des items dans votre boutique avec `;shop`", mention_author=False)
        
        item = shop[itemid]
        if qte and 'qte' in item:
            if qte < item['qte']:
                await self.config.member(user).Shop.set_raw(itemid, 'qte', value = item['qte'] - qte)
                txt = f"**Quantité réduite** • L'item *{item['name']}* (`{itemid}`) n'est désormais disponible qu'en {item['qte'] - qte} exemplaires"
            elif qte == item['qte']:
                await self.config.member(user).Shop.clear_raw(itemid)
                txt = f"**Item supprimé** • L'item *{item['name']}* (`{itemid}`) n'est désormais plus disponible dans votre boutique (quantité nulle)"
                
                for mid in manualids:
                    if manualids[mid]['item'] == itemid:
                        await self.config.member(user).ManualIDs.clear_raw(mid)
            else:
                txt = f"**Erreur** • L'item *{item['name']}* (`{itemid}`) n'est disponible qu'en {item['qte']} exemplaires et vous tentez d'en retirer {qte} ce qui est impossible"
            await ctx.reply(txt, mention_author=False)
        else:
            await self.config.member(user).Shop.clear_raw(itemid)
            await ctx.reply(f"**Item supprimé** • L'item *{item['name']}* (`{itemid}`) n'est désormais plus disponible dans votre boutique", mention_author=False)
            
            for mid in manualids:
                if manualids[mid]['item'] == itemid:
                    await self.config.member(user).ManualIDs.clear_raw(mid)
    
    @member_shop_commands.command(name='reset', hidden=True)
    async def shop_reset(self, ctx):
        """Reset entièrement votre boutique"""
        user = ctx.author
        await self.config.member(user).Shop.clear()
        await ctx.reply("**Reset effectué** • Tous les items de votre boutique ont été retirés.")
        
    @commands.command(name="preuve", aliases=['proof'])
    async def get_operation_proof(self, ctx, logid: str):
        """Récupérer la preuve de paiement à partir de son identifiant"""
        ope = await self.get_log_ticket(ctx.guild, logid)
        if ope:
            await ctx.reply(embed=ope, mention_author=False)
        else:
            await ctx.reply("**Erreur** • Cet identifiant est invalide ou la durée maximale de conservation de ce ticket a été atteinte")
    
    
    @commands.group(name='contract', aliases=['contrat'], invoke_without_command=True)
    @commands.guild_only()
    async def contracts_commands(self, ctx, contract_id: str):
        """Voir et créer des contrats manuels entre plusieurs membres"""
        if ctx.invoked_subcommand is None:
            return await ctx.invoke(self.show_contract, contract_id = contract_id)
    
    @contracts_commands.command(name="show")
    async def show_contract(self, ctx, contract_id: str):
        """Affiche les détails d'un contrat conclu entre plusieurs membres à partir de son identifiant unique
        
        Ne pas saisir le symbole $ au début de l'ID"""
        con = await self.get_contract_info(ctx.guild, contract_id)
        if con:
            await ctx.reply(embed=con, mention_author=False)
        else:
            await ctx.reply("**Erreur** • Cet identifiant est invalide ou la durée maximale de conservation de ce contrat a été atteinte")
        
    @contracts_commands.command(name="new")
    async def create_contract(self, ctx, members: commands.Greedy[discord.Member]):
        """Créer un nouveau contrat entre ces membres
        
        Vous devez vous mentionner vous-même pour vous inclure au contrat
        Cette commande démarre un processus étape par étape de création d'un contrat"""
        author = ctx.author
        eco = self.bot.get_cog('AltEco')
        curr = await eco.get_currency(ctx.guild)
        
        if len(members) < 2:
            return await ctx.reply(f"**Aucune partie au contrat** • Vous devez accompagner la commande des mentions (ou liste de pseudos exactes, entre guillemets) des parties au contrat, y compris vous-même si vous en êtes une", mention_author=False)
        
        
        await ctx.reply(f"**Processus de création d'un contrat** • Vous allez être guidé à travers les différentes étapes de création d'un contrat. En cas d'erreur, vous devrez refaire la commande et refaire chaque étape.\nVous pouvez dire 'stop' à tout moment pour arrêter.", mention_author=False)
        await asyncio.sleep(3)
        
        async def query_value(desc: str, timeout_delay: int = 30):
            qem = discord.Embed(description=desc, color = discord.Color.dark_gray())
            qem.set_footer(text=f"››› Entrez l'élement ci-dessous ({timeout_delay}s)")
            await ctx.send(embed=qem)
            try:
                resp = await self.bot.wait_for('message',
                                               timeout=timeout_delay,
                                               check=lambda m: m.author == ctx.author and m.channel == ctx.channel)
            except asyncio.TimeoutError:
                return None
            if resp.content.lower() in ('stop', 'annuler', 'quitter', 'aucun', 'aucune', 'rien'):
                return None
            return resp.content
        
        content = await query_value("**A. Objet du contrat :** Vous devez décrire précisement l'objet du contrat et les conditions fixées pour les différentes parties au contrat (Max. 1000 caractères).\nSi le contrat concerne une somme de crédits, vous pourrez la préciser à la prochaine étape.", 600)
        if not content:
            return await ctx.send("Création du contrat annulée")
        elif len(content) > 1000:
            return await ctx.send("**Objet du contrat invalide** • Celui-ci ne peut faire plus de 1000 caractères")
        await asyncio.sleep(0.5)
        
        creditssum = await query_value("**B. Somme de crédits :** Somme concernée par le contrat.\nS'il n'y a aucune somme concernée ou si vous ne désirez pas la préciser, entrez '0'.", 60)
        if not creditssum:
            return await ctx.send("Création du contrat annulée")
        try:
            creditssum = int(creditssum)
            if creditssum < 0:
                return await ctx.send("**Somme invalide** • Le nombre est invalide car négatif")
        except:
            return await ctx.send("**Somme invalide** • Nombre introuvable dans votre réponse")
        await asyncio.sleep(0.5)
        
        expiration_date = await query_value("**C. Date limite :** Date à laquelle le contrat ne sera plus valide, qu'il aura expiré.\nElle doit être au format `JJ/MM/AAAA`.\nCette date est obligatoire même si elle est lointaine, après cette date le contrat sera supprimé des données du bot.", 120)
        
        if not expiration_date:
            return await ctx.send("Création du contrat annulée")
        try:
            exp_txt = expiration_date
            expiration_date = datetime.strptime(expiration_date, '%d/%m/%Y')
        except:
            return await ctx.send("**Date invalide** • Suivez le format `JJ/MM/AAAA`, ex. 07/08/2021")
        else:
            expiration_date = expiration_date.timestamp()
            if expiration_date <= time.time() + 3600:
                return await ctx.send("**Date invalide** • Impossible de mettre une date trop proche (<1h avec maintenant) ou déjà passée")
        await asyncio.sleep(0.5)
        
        lm = {m.id : False for m in members}
        msg = None
        timeout = time.time() + 300
        while time.time() <= timeout and not all([lm[i] for i in lm]):
            lm_emojis = [(ctx.guild.get_member(i), '✅' if lm[i] else '❎') for i in lm]
            resume = f"__**Objet du contrat :**__ {content}\n**__Crédits concernés :__** {creditssum if creditssum else 'N.R.'}{curr}\n**__Expire le :__** {exp_txt}"
            em = discord.Embed(title=f"Résumé du contrat créé",
                            description=resume,
                            color=discord.Color.dark_gray())
            em.add_field(name="Parties au contrat", value=box(tabulate(lm_emojis, headers=('Membre', 'Accepté ?'))))
            em.set_footer(text="››› En attente de la confirmation de chaque membre partie au contrat [Valide 5m]")
            if not msg:
                msg = await ctx.send(embed=em)
                start_adding_reactions(msg, ['✅'])
            else:
                await msg.edit(embed=em)
            
            try:
                react, ruser = await self.bot.wait_for("reaction_add",
                                                check=lambda m, u: u in members and m.message.id == msg.id,
                                                timeout=300)
            except asyncio.TimeoutError:
                continue
            
            if react.emoji == '✅':
                if not lm[ruser.id]:
                    lm[ruser.id] = True
        
        if not all([lm[i] for i in lm]):
            await msg.delete()
            return await ctx.send("**Contrat annulé** • Toutes les parties au contrat n'ont pas accepté dans les temps (5 minutes).")
        
        lm_emojis = [(ctx.guild.get_member(i), '✅' if lm[i] else '❎') for i in lm]
        resume = f"__**Objet du contrat :**__ {content}\n**__Crédits concernés :__** {creditssum if creditssum else 'N.R.'}{curr}\n**__Expire le :__** {exp_txt}"
        em = discord.Embed(title=f"Résumé du contrat créé",
                        description=resume,
                        color=discord.Color.green())
        em.add_field(name="Parties au contrat", value=box(tabulate(lm_emojis, headers=('Membre', 'Accepté ?'))))
        em.set_footer(text="Toutes les parties ont accepté le contrat")
        
        contract = {'members': members, 'content': content, 'expiration_date': expiration_date, 'credits': creditssum if creditssum else None}
        uid = await self.log_contract(ctx.guild, **contract)
        await ctx.send(f"✅ **Succès** • Le contrat `${uid}` a été créé et pourra être consulté en entrant la commande `;contract {uid}`", 
                       embed=await self.get_contract_info(ctx.guild, uid))
        
        