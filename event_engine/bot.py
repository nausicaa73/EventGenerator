import discord
import re
from discord.ext import commands

from event_engine.event_manager import EventManager
from event_engine.activity_manager import ActivityManager


class EventCommands(commands.Cog):
    """Commandes Discord liées aux événements."""

    def __init__(self, manager):
        self.manager = manager
        self.activities = ActivityManager(manager)

    async def resolve_event_id(
        self,
        ctx,
        event_id: str | None,
        *,
        joined_only: bool,
        command_name: str,
    ) -> str | None:
        """Détermine l'événement ou demande à l'utilisateur de le préciser."""

        if event_id:
            return event_id

        if joined_only:
            event_ids = self.manager.get_joined_event_ids(
                ctx.guild.id,
                ctx.author.id,
            )
        else:
            event_ids = self.manager.get_active_event_ids(ctx.guild.id)

        if not event_ids:
            if joined_only:
                await ctx.send(
                    "Tu n'es inscrit à aucun événement actif sur ce serveur."
                )
            else:
                await ctx.send(
                    "Aucun événement actif n'est disponible sur ce serveur."
                )
            return None

        if len(event_ids) == 1:
            return event_ids[0]

        options = "\n".join(
            f"• `{event_id}` — "
            f"{self.manager.get_event(event_id)['name']}"
            for event_id in event_ids
        )

        await ctx.send(
            "Plusieurs événements sont possibles. "
            f"Précise l'identifiant avec `*event {command_name} ID`.\n\n"
            f"{options}"
        )
        return None

    async def inactive_event_message(self, ctx, event_id: str) -> bool:
        """Explique pourquoi un événement ne permet pas de jouer."""
        event = self.manager.get_event(event_id)
        if not event:
            return False

        from datetime import datetime, timezone
        now = datetime.now()

        def parse_date(key):
            value = event.get(key)
            if not value:
                return None
            try:
                return datetime.fromisoformat(value)
            except (TypeError, ValueError):
                return None

        start = parse_date("start_date")
        end = parse_date("end_date")

        def compare_now(moment):
            if moment is None:
                return now
            if moment.tzinfo:
                return datetime.now(timezone.utc).astimezone(moment.tzinfo)
            return datetime.now()

        if start is not None and compare_now(start) < start:
            await ctx.send(
                f"L'événement **{event.get('name', event_id)}** (`{event_id}`) "
                f"n'a pas encore commencé. Début prévu : **{event['start_date']}**."
            )
            return True

        try:
            ended = self.manager._event_has_ended(event_id)
        except ValueError:
            ended = False
        if ended:
            end_label = event.get("end_date", "date inconnue")
            await ctx.send(
                f"L'événement **{event.get('name', event_id)}** (`{event_id}`) "
                f"est terminé depuis le **{end_label}**. Les activités ne sont "
                "plus accessibles ; les données et récompenses des joueurs sont conservées."
            )
            return True
        return False

    async def resolve_activity(
        self,
        ctx,
        activity_id: str,
        event_id: str | None = None,
        *,
        joined_only: bool = False,
        command_name: str = "activity",
    ):
        active_ids = self.manager.get_active_event_ids(ctx.guild.id)

        if event_id is not None:
            if event_id not in active_ids:
                if await self.inactive_event_message(ctx, event_id):
                    return None
                await ctx.send(
                    f"L'événement `{event_id}` n'est pas actif sur ce serveur. "
                    f"Un administrateur peut le lancer avec `*event start {event_id}` "
                    "si sa période est valide."
                )
                return None
            candidates = [event_id]
        elif joined_only:
            candidates = self.manager.get_joined_event_ids(
                ctx.guild.id,
                ctx.author.id,
            )
        else:
            candidates = active_ids

        matches = []
        invalid_events = []

        for candidate_id in candidates:
            try:
                activity = self.activities.get_activity(
                    candidate_id,
                    activity_id,
                )
            except (ValueError, OSError) as error:
                invalid_events.append((candidate_id, str(error)))
                continue

            if activity is not None:
                matches.append((candidate_id, activity))

        if invalid_events and not matches:
            details = "\n".join(
                f"• `{candidate_id}` : {error}"
                for candidate_id, error in invalid_events
            )
            await ctx.send(
                "Je n'ai trouvé aucune correspondance dans les événements "
                "valides, mais certains fichiers n'ont pas pu être lus :\n"
                f"{details}"
            )
            return None

        if not matches:
            if joined_only:
                active_matches = []

                for candidate_id in active_ids:
                    try:
                        activity = self.activities.get_activity(
                            candidate_id,
                            activity_id,
                        )
                    except (ValueError, OSError):
                        continue

                    if activity is not None:
                        active_matches.append(candidate_id)

                if active_matches:
                    await ctx.send(
                        "Tu dois rejoindre l'événement avant de participer. "
                        "Utilise `*event join ID`.\n"
                        "Événements concernés : "
                        + ", ".join(f"`{item}`" for item in active_matches)
                    )
                    return None

            # Si l'activité existe dans le catalogue mais que l'événement n'est
            # plus actif, expliquer l'état au lieu de prétendre qu'elle n'existe pas.
            for candidate_id, event in self.manager.events.items():
                if candidate_id in active_ids or not event.get("enabled", True):
                    continue
                try:
                    inactive_activity = self.activities.get_activity(candidate_id, activity_id)
                except (ValueError, OSError):
                    continue
                if inactive_activity is not None and await self.inactive_event_message(ctx, candidate_id):
                    return None

            await ctx.send(
                f"Aucune activité `{activity_id}` correspondante n'a été trouvée "
                "dans les événements actifs. Vérifie son identifiant avec "
                "`*event activities [ID]` ou consulte `*event list`."
            )
            return None

        if len(matches) > 1:
            options = "\n".join(
                f"• `{candidate_id}` — "
                f"{self.manager.get_event(candidate_id)['name']}"
                for candidate_id, _ in matches
            )

            if command_name == "answer":
                syntax = (
                    f"`*event answer ID_ÉVÉNEMENT "
                    f"{activity_id} RÉPONSE`"
                )
            else:
                syntax = (
                    f"`*event {command_name} "
                    f"{activity_id} ID_ÉVÉNEMENT`"
                )

            await ctx.send(
                f"L'activité `{activity_id}` existe dans plusieurs "
                f"événements. Précise lequel avec {syntax}.\n\n"
                f"{options}"
            )
            return None

        resolved_event_id, activity = matches[0]

        if joined_only:
            joined_ids = self.manager.get_joined_event_ids(
                ctx.guild.id,
                ctx.author.id,
            )
            if resolved_event_id not in joined_ids:
                await ctx.send(
                    f"Tu dois d'abord rejoindre **{resolved_event_id}** "
                    f"avec `*event join {resolved_event_id}`."
                )
                return None

        return resolved_event_id, activity


    @commands.group(name="event", invoke_without_command=True)
    async def event(self, ctx, activity_id: str | None = None, event_id: str | None = None):
        # Une activité de type commande peut être lancée directement : *event bonbon.
        if activity_id is not None:
            await self.run_command_activity(ctx, activity_id, event_id)
            return
        await ctx.send(
            "**Commandes des événements**\n\n"
            "**Découvrir les événements**\n"
            "`*event list` — Lister les événements disponibles\n"
            "`*event info ID` — Consulter la description et les dates d'un événement\n"
            "`*event start ID` — Lancer un événement (permission Gérer le serveur)\n"
            "`*event stop [ID]` — Arrêter un événement (permission Gérer le serveur)\n\n"
            "**Joueur**\n"
            "`*event join [ID]` — Rejoindre un événement\n"
            "`*event profile [ID] [joueur]` — Afficher un profil (mention ou ID Discord)\n"
            "Exemples : `*event profile`, `*event profile @Joueur`, `*event profile halloween_2026 @Joueur`, `*event profile 123456789012345678 halloween_2026`\n"
            "`*event ranking [ID] [points|monnaie]` — Afficher le classement, par points par défaut\n"
            "Exemples : `*event ranking`, `*event ranking bonbons`, `*event ranking halloween_2026 bonbons`\n\n"
            "**Activités**\n"
            "`*event activities [ID]` — Lister les activités d'un événement\n"
            "`*event activity ACTIVITÉ [ID]` — Consulter une activité\n"
            "`*event answer ACTIVITÉ RÉPONSE` — Répondre à un quiz ou une énigme\n"
            "`*event answer ID ACTIVITÉ RÉPONSE` — Variante avec l'événement précisé\n"
            "`*event ACTIVITÉ [ID]` — Lancer directement une activité à commande (ex. `*event bonbon`)\n"
            "`*event do ACTIVITÉ [ID]` — Ancienne syntaxe, conservée comme alias\n\n"
            "`[ID]` est facultatif lorsqu'un seul événement correspond ; sinon, précise son identifiant."
        )

    @event.command(name="list")
    async def event_list(self, ctx):
        events = self.manager.list_events()

        if not events:
            await ctx.send(
                "Aucun événement n'est disponible actuellement."
            )
            return

        embed = discord.Embed(
            title="Catalogue des événements",
            description="Événements disponibles au lancement.",
            color=discord.Color.dark_purple(),
        )

        for event in events[:25]:
            embed.add_field(
                name=f"{event['name']} — `{event['id']}`",
                value=event["description"][:1024],
                inline=False,
            )

        if len(events) > 25:
            embed.set_footer(
                text=(
                    f"{len(events) - 25} autre(s) événement(s) "
                    "non affiché(s)."
                )
            )

        await ctx.send(embed=embed)

    @event.command(name="info")
    async def event_info(self, ctx, event_id: str):
        event = self.manager.get_event(event_id)

        if event is None or not event.get("enabled", True):
            await ctx.send(
                "Cet événement n'existe pas ou n'est pas disponible."
            )
            return

        embed = discord.Embed(
            title=event["name"],
            description=event["description"],
            color=discord.Color.dark_purple(),
        )
        embed.add_field(
            name="ID",
            value=event["id"],
            inline=True,
        )

        if event.get("start_date"):
            embed.add_field(
                name="Début des lancements",
                value=event["start_date"],
                inline=False,
            )

        if event.get("end_date"):
            embed.add_field(
                name="Fin des lancements",
                value=event["end_date"],
                inline=False,
            )

        await ctx.send(embed=embed)

    @event.command(name="start")
    @commands.guild_only()
    @commands.has_guild_permissions(manage_guild=True)
    async def event_start(self, ctx, event_id: str):
        try:
            database_path = self.manager.start_event(
                ctx.guild.id,
                event_id,
            )
        except (ValueError, FileExistsError) as error:
            await ctx.send(
                f"Impossible de lancer l'événement : {error}"
            )
            return

        await ctx.send(
            f"**{event_id}** est lancé sur ce serveur !\n"
            f"Base de données créée : `{database_path.name}`"
        )

    @event.command(name="stop", aliases=["end", "stopper", "close"])
    @commands.guild_only()
    @commands.has_guild_permissions(manage_guild=True)
    async def event_stop(self, ctx, event_id: str | None = None):
        event_id = await self.resolve_event_id(
            ctx, event_id, joined_only=False, command_name="stop"
        )
        if event_id is None:
            return
        try:
            stopped = self.manager.stop_event(ctx.guild.id, event_id)
        except (ValueError, OSError) as error:
            await ctx.send(f"Impossible d'arrêter l'événement : {error}")
            return
        if stopped:
            await ctx.send(f"L'événement **{event_id}** est arrêté. Les données des joueurs sont conservées.")
        else:
            await ctx.send(f"L'événement **{event_id}** n'est pas actif sur ce serveur.")

    @event.command(name="join")
    @commands.guild_only()
    async def event_join(self, ctx, event_id: str | None = None):
        if ctx.author.bot:
            return

        event_id = await self.resolve_event_id(
            ctx,
            event_id,
            joined_only=False,
            command_name="join",
        )

        if event_id is None:
            return

        try:
            joined = self.manager.join_player(
                ctx.guild.id,
                event_id,
                ctx.author.id,
            )
        except (ValueError, FileNotFoundError) as error:
            await ctx.send(f"Impossible de rejoindre l'événement : {error}")
            return

        if joined:
            await ctx.send(f"Tu as rejoint **{event_id}** !")
        else:
            await ctx.send("Tu es déjà inscrit à cet événement.")

    @event.command(name="profile")
    @commands.guild_only()
    async def event_profile(
        self,
        ctx,
        first: str | None = None,
        second: str | None = None,
    ):
        """Syntaxes : profile [event_id] [joueur] ou profile [joueur] [event_id]."""
        target = ctx.author
        event_id = None
        member_pattern = re.compile(r"^<@!?(\d+)>$")

        async def resolve_member(token: str | None):
            if not token:
                return None
            match = member_pattern.fullmatch(token)
            raw_id = match.group(1) if match else token
            if not raw_id.isdigit():
                return None
            member_id = int(raw_id)
            member = ctx.guild.get_member(member_id)
            if member is None:
                try:
                    member = await ctx.guild.fetch_member(member_id)
                except (discord.NotFound, discord.Forbidden, discord.HTTPException):
                    return None
            return member

        first_member = await resolve_member(first)
        second_member = await resolve_member(second)
        if first_member is not None:
            target = first_member
            event_id = second if second and second not in (target.mention, str(target.id)) else None
        elif second_member is not None:
            event_id = first
            target = second_member
        elif first is not None and first in self.manager.get_active_event_ids(ctx.guild.id):
            event_id = first
            if second is not None:
                target = await resolve_member(second)
                if target is None:
                    await ctx.send("Joueur introuvable. Mentionne le membre ou indique son ID Discord.")
                    return
        elif first is not None and first.isdigit():
            target = await resolve_member(first)
            if target is None:
                await ctx.send("Joueur introuvable sur ce serveur. Utilise une mention ou un ID Discord valide.")
                return
            event_id = second
        elif first is not None:
            # Si le premier argument n'est pas un membre, on le traite comme l'ID d'événement.
            event_id = first
            if second is not None:
                target = await resolve_member(second)
                if target is None:
                    await ctx.send("Joueur introuvable. Mentionne le membre ou indique son ID Discord.")
                    return

        if event_id is None:
            if target.id == ctx.author.id:
                event_id = await self.resolve_event_id(
                    ctx, None, joined_only=True, command_name="profile"
                )
            else:
                joined_ids = self.manager.get_joined_event_ids(ctx.guild.id, target.id)
                if not joined_ids:
                    await ctx.send(f"{target.display_name} n'est inscrit à aucun événement actif sur ce serveur.")
                    return
                if len(joined_ids) == 1:
                    event_id = joined_ids[0]
                else:
                    options = "\n".join(
                        f"• `{eid}` — {self.manager.get_event(eid)['name']}"
                        for eid in joined_ids
                    )
                    await ctx.send(
                        f"Plusieurs événements correspondent au profil de {target.display_name}. "
                        f"Précise l'ID : `*event profile ID @{target.display_name}`\n{options}"
                    )
                    return
        if event_id is None:
            return

        try:
            profile = self.manager.get_player_profile(ctx.guild.id, event_id, target.id)
        except (ValueError, FileNotFoundError) as error:
            await ctx.send(f"Impossible de consulter le profil : {error}")
            return

        if profile is None:
            await ctx.send(f"{target.display_name} n'est pas inscrit à **{event_id}**.")
            return

        event = self.manager.get_event(event_id)
        currency_name = event.get("currency", "monnaie")
        embed = discord.Embed(
            title=f"Profil — {event['name']}",
            color=discord.Color.dark_purple(),
        )
        embed.set_author(name=target.display_name, icon_url=target.display_avatar.url)
        embed.add_field(name="Points", value=str(profile["points"]), inline=True)
        embed.add_field(name=currency_name.capitalize(), value=str(profile["currency"]), inline=True)
        embed.add_field(name="Inscription", value=profile["joined_at"], inline=False)
        await ctx.send(embed=embed)

    @event.command(name="ranking")
    @commands.guild_only()
    async def event_ranking(
        self,
        ctx,
        first: str | None = None,
        second: str | None = None,
    ):
        active_ids = self.manager.get_active_event_ids(ctx.guild.id)
        sort_by = "points"
        event_id = None

        # Syntaxes : ranking ; ranking bonbons ; ranking ID ; ranking ID bonbons
        if first in active_ids:
            event_id = first
            if second:
                sort_by = second.casefold()
        elif first:
            possible_sort = first.casefold()
            if possible_sort in ("points", "point", "currency", "monnaie", "bonbons"):
                sort_by = possible_sort
            else:
                event_id = first
                if second:
                    sort_by = second.casefold()

        event_id = await self.resolve_event_id(
            ctx, event_id, joined_only=False, command_name="ranking"
        )
        if event_id is None:
            return

        event = self.manager.get_event(event_id)
        currency_name = event.get("currency", "monnaie").casefold()
        if sort_by in ("point", "points"):
            sort_by = "points"
        elif sort_by in ("currency", "monnaie", currency_name):
            sort_by = "currency"
        else:
            await ctx.send(
                f"Critère inconnu `{sort_by}`. Utilise `points` ou `{event.get('currency', 'monnaie')}`."
            )
            return

        try:
            ranking = self.manager.get_ranking(ctx.guild.id, event_id, sort_by=sort_by)
        except (ValueError, FileNotFoundError) as error:
            await ctx.send(f"Impossible d'afficher le classement : {error}")
            return

        if not ranking:
            await ctx.send("Aucun joueur n'est inscrit à cet événement.")
            return

        label = "points" if sort_by == "points" else event.get("currency", "monnaie")
        embed = discord.Embed(
            title=f"Classement — {event['name']} ({label})",
            color=discord.Color.dark_purple(),
        )
        for position, player in enumerate(ranking, start=1):
            user_id = player["user_id"]
            member = ctx.guild.get_member(user_id)
            if member is None:
                try:
                    member = await ctx.guild.fetch_member(user_id)
                    username = member.display_name
                except (discord.NotFound, discord.Forbidden):
                    user = ctx.bot.get_user(user_id)
                    if user is None:
                        try:
                            user = await ctx.bot.fetch_user(user_id)
                        except (discord.NotFound, discord.HTTPException):
                            user = None
                    username = user.name if user else "Utilisateur inconnu"
            else:
                username = member.display_name

            currency_name = event.get("currency", "monnaie")
            embed.add_field(
                name=f"{position}. {username}",
                value=(
                    f"**{player['points']} points** · "
                    f"**{player['currency']} {currency_name}**"
                ),
                inline=False,
            )
        embed.set_footer(text="Classement des 10 meilleurs joueurs")
        await ctx.send(embed=embed)

    @event.command(name="activities")
    @commands.guild_only()
    async def event_activities(
        self,
        ctx,
        event_id: str | None = None,
    ):
        active_ids = self.manager.get_active_event_ids(ctx.guild.id)

        if event_id is not None:
            if event_id not in active_ids:
                await ctx.send(
                    f"L'événement `{event_id}` n'est pas actif sur ce serveur."
                )
                return
            candidates = [event_id]
        else:
            candidates = active_ids

        if not candidates:
            await ctx.send("Aucun événement actif sur ce serveur.")
            return

        if len(candidates) > 1:
            options = "\n".join(f"• `{item}`" for item in candidates)
            await ctx.send(
                "Plusieurs événements sont actifs. "
                "Précise lequel consulter avec `*event activities ID`.\n\n"
                + options
            )
            return

        event_id = candidates[0]
        event = self.manager.get_event(event_id)

        try:
            activities = self.activities.get_activities(event_id)
        except (ValueError, OSError) as error:
            await ctx.send(f"Impossible de charger les activités : {error}")
            return

        if not activities:
            await ctx.send(
                f"Aucune activité configurée pour **{event['name']}**."
            )
            return

        embed = discord.Embed(
            title=f"Activités — {event['name']}",
            color=discord.Color.dark_purple(),
        )

        for activity in activities[:25]:
            activity_type = {
                "quiz": "Quiz",
                "riddle": "Énigme",
                "command": "Commande récompensée",
            }[activity["type"]]

            embed.add_field(
                name=f"{activity['name']} (`{activity['id']}`)",
                value=(
                    f"{activity.get('description', '')}\n"
                    f"Type : {activity_type}"
                ),
                inline=False,
            )

        await ctx.send(embed=embed)

    @event.command(name="activity")
    @commands.guild_only()
    async def event_activity(
        self,
        ctx,
        activity_id: str,
        event_id: str | None = None,
    ):
        try:
            result = await self.resolve_activity(
                ctx,
                activity_id,
                event_id,
                command_name="activity",
            )
        except (ValueError, OSError) as error:
            await ctx.send(f"Impossible de charger l'activité : {error}")
            return

        if result is None:
            return

        resolved_event_id, activity = result
        event = self.manager.get_event(resolved_event_id)

        embed = discord.Embed(
            title=activity["name"],
            description=activity.get("description", ""),
            color=discord.Color.dark_purple(),
        )

        if activity["type"] in ("quiz", "riddle"):
            embed.add_field(
                name="Défi",
                value=activity["question"],
                inline=False,
            )

            choices = activity.get("choices", [])

            if choices:
                embed.add_field(
                    name="Choix",
                    value="\n".join(choices),
                    inline=False,
                )

            embed.add_field(
                name="Répondre",
                value=f"`*event answer {activity_id} VOTRE_RÉPONSE`",
                inline=False,
            )
        else:
            embed.add_field(
                name="Utilisation",
                value=f"`*event do {activity_id}`",
                inline=False,
            )

            cooldown = activity.get("cooldown_seconds", 86400)
            embed.add_field(
                name="Cooldown",
                value=f"{cooldown // 3600} h {(cooldown % 3600) // 60} min",
                inline=True,
            )

        embed.add_field(
            name="Récompense",
            value=(
                f"{activity.get('rewards', {}).get('points', 0)} points, "
                f"{activity.get('rewards', {}).get('currency', 0)} "
                f"{event.get('currency', 'monnaie')}"
            ),
            inline=True,
        )

        embed.set_footer(text=f"Événement : {resolved_event_id}")
        await ctx.send(embed=embed)


    @event.command(name="answer")
    @commands.guild_only()
    async def event_answer(
        self,
        ctx,
        first: str,
        second: str,
        *,
        rest: str = "",
    ):
        # Forme explicite :
        # *event answer halloween_2026 quiz_capital Paris
        if first in self.manager.events:
            event_id = first
            activity_id = second
            answer = rest.strip()

            if not answer:
                await ctx.send(
                    "Indique ta réponse après l'identifiant de l'activité."
                )
                return
        else:
            # Forme courte :
            # *event answer quiz_capital Paris
            # *event answer riddle_pumpkin une citrouille
            event_id = None
            activity_id = first
            answer = f"{second} {rest}".strip()

        try:
            result = await self.resolve_activity(
                ctx,
                activity_id,
                event_id,
                joined_only=True,
                command_name="answer",
            )

            if result is None:
                return

            resolved_event_id, _ = result

            outcome = self.activities.answer(
                ctx.guild.id,
                resolved_event_id,
                ctx.author.id,
                activity_id,
                answer,
            )
        except Exception as error:
            import traceback
            traceback.print_exc()
            await ctx.send(
                f"Impossible de répondre ({type(error).__name__}) : {error}"
            )
            return
        status = outcome["status"]

        if status == "not_joined":
            await ctx.send(
                f"Tu dois rejoindre l'événement avec "
                f"`*event join {resolved_event_id}`."
            )
        elif status == "completed":
            await ctx.send("Tu as déjà réussi cette activité.")
        elif status == "exhausted":
            await ctx.send(
                "Tu as utilisé toutes tes tentatives pour cette activité."
            )
        elif status == "cooldown":
            remaining = outcome["remaining"]
            await ctx.send(
                f"Tu dois attendre encore {remaining // 60} minute(s)."
            )
        elif status == "wrong":
            max_attempts = outcome["max_attempts"]
            message = "Ce n'est pas la bonne réponse."

            if max_attempts is not None:
                remaining = max_attempts - outcome["attempts"]
                message += f" Il te reste {remaining} tentative(s)."

            await ctx.send(message)
        elif status == "correct":
            rewards = outcome["rewards"]
            event = self.manager.get_event(resolved_event_id)
            currency = event.get("currency", "monnaie")

            await ctx.send(
                f"Bonne réponse, {ctx.author.display_name} ! "
                f"Tu gagnes {rewards.get('points', 0)} points et "
                f"{rewards.get('currency', 0)} {currency}."
            )

    @event.command(name="do")
    @commands.guild_only()
    async def event_do(
        self,
        ctx,
        activity_id: str,
        event_id: str | None = None,
    ):
        await self.run_command_activity(ctx, activity_id, event_id)

    async def run_command_activity(
        self, ctx, activity_id: str, event_id: str | None = None
    ):
        if ctx.guild is None:
            await ctx.send("Cette commande doit être utilisée sur un serveur Discord.")
            return
        try:
            result = await self.resolve_activity(
                ctx, activity_id, event_id,
                joined_only=True, command_name="do",
            )
            if result is None:
                return
            resolved_event_id, activity = result
            outcome = self.activities.claim_command(
                ctx.guild.id, resolved_event_id, ctx.author.id, activity_id
            )
        except (ValueError, OSError) as error:
            await ctx.send(f"Impossible d'effectuer l'activité : {error}")
            return

        status = outcome["status"]
        if status == "not_joined":
            await ctx.send(
                f"Tu dois d'abord rejoindre l'événement avec `*event join {resolved_event_id}`."
            )
        elif status == "completed":
            await ctx.send("Tu as déjà obtenu la récompense de cette activité.")
        elif status == "cooldown":
            remaining = outcome["remaining"]
            hours, remainder = divmod(remaining, 3600)
            minutes = remainder // 60
            seconds = remainder % 60
            await ctx.send(
                f"Tu as déjà utilisé cette commande récemment. Réessaie dans "
                f"{hours} h {minutes} min {seconds} s."
            )
        elif status == "success":
            message = outcome.get("message")
            if not message:
                rewards = outcome.get("rewards", {})
                event = self.manager.get_event(resolved_event_id)
                currency = event.get("currency", "monnaie")
                message = (
                    f"Récompense obtenue ! Tu gagnes {rewards.get('points', 0)} points "
                    f"et {rewards.get('currency', 0)} {currency}."
                )

            image = outcome.get("image")
            if image:
                event_dir = self.manager._safe_path(f"events/{resolved_event_id}")
                image_path = (event_dir / image).resolve()
                if not image_path.is_relative_to(event_dir) or not image_path.is_file():
                    await ctx.send(
                        f"L'image configurée pour cette activité est introuvable ou invalide : `{image}`."
                    )
                    return
                await ctx.send(content=message, file=discord.File(str(image_path)))
            else:
                await ctx.send(message)



class EventBot(commands.Bot):
    def __init__(self, project_dir):
        self.manager = EventManager(project_dir)

        prefix = self.manager.settings.get("command_prefix", "*")

        intents = discord.Intents.default()
        intents.message_content = True

        super().__init__(
            command_prefix=prefix,
            intents=intents,
        )

    async def setup_hook(self):
        await self.add_cog(EventCommands(self.manager))

        print(f"{len(self.manager.events)} événement(s) chargé(s).")
        print(
            "Commandes enregistrées :",
            [cmd.name for cmd in self.commands],
        )

    async def on_ready(self):
        print(f"Bot connecté : {self.user}")
        print(f"Préfixe des commandes : {self.command_prefix}")

    async def on_command(self, ctx):
        print(
            f"[COMMANDE] {ctx.author} : "
            f"{ctx.message.content!r} "
            f"-> {ctx.command}"
        )

    async def on_command_error(self, ctx, error):
        print(
            f"[ERREUR COMMANDE] {ctx.message.content!r} : "
            f"{type(error).__name__}: {error}"
        )

        if isinstance(error, commands.CommandNotFound):
            return

        if isinstance(error, commands.MissingPermissions):
            await ctx.send(
                "Tu dois disposer de la permission « Gérer le serveur »."
            )
            return

        if isinstance(error, commands.NoPrivateMessage):
            await ctx.send(
                "Cette commande doit être utilisée sur un serveur."
            )
            return

        await ctx.send(
            f"Une erreur est survenue : "
            f"`{type(error).__name__}`"
        )
   