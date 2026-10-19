import discord
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
                await ctx.send(
                    f"L'événement `{event_id}` n'est pas actif sur ce serveur."
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

            await ctx.send(
                f"Aucune activité `{activity_id}` correspondante "
                "n'a été trouvée parmi les événements sélectionnés."
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
    async def event(self, ctx):
        await ctx.send(
            "**Commandes des événements**\n"
            "`*event list` — Lister les événements\n"
            "`*event info ID` — Consulter un événement\n"
            "`*event start ID` — Lancer un événement\n"
            "`*event activities [ID]` — Lister les activités\n"
            "`*event activity ACTIVITÉ [ID]` — Consulter une activité\n"
            "`*event answer ACTIVITÉ RÉPONSE` — Répondre à un défi\n"
            "`*event do ACTIVITÉ [ID]` — Réclamer une récompense"
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
    async def event_profile(self, ctx, event_id: str | None = None):
        event_id = await self.resolve_event_id(
            ctx,
            event_id,
            joined_only=True,
            command_name="profile",
        )

        if event_id is None:
            return

        try:
            profile = self.manager.get_player_profile(
                ctx.guild.id,
                event_id,
                ctx.author.id,
            )
        except (ValueError, FileNotFoundError) as error:
            await ctx.send(f"Impossible de consulter le profil : {error}")
            return

        if profile is None:
            await ctx.send(
                f"Tu n'es pas inscrit à **{event_id}**. "
                f"Utilise `*event join {event_id}`."
            )
            return

        event = self.manager.get_event(event_id)
        currency_name = event.get("currency", "monnaie")

        embed = discord.Embed(
            title=f"Profil — {event['name']}",
            color=discord.Color.dark_purple(),
        )
        embed.set_author(
            name=ctx.author.display_name,
            icon_url=ctx.author.display_avatar.url,
        )
        embed.add_field(
            name="Points",
            value=str(profile["points"]),
            inline=True,
        )
        embed.add_field(
            name=currency_name.capitalize(),
            value=str(profile["currency"]),
            inline=True,
        )
        embed.add_field(
            name="Inscription",
            value=profile["joined_at"],
            inline=False,
        )

        await ctx.send(embed=embed)

    @event.command(name="ranking")
    @commands.guild_only()
    async def event_ranking(self, ctx, event_id: str | None = None):
        event_id = await self.resolve_event_id(
            ctx,
            event_id,
            joined_only=False,
            command_name="ranking",
        )

        if event_id is None:
            return

        try:
            ranking = self.manager.get_ranking(
                ctx.guild.id,
                event_id,
            )
        except (ValueError, FileNotFoundError) as error:
            await ctx.send(f"Impossible d'afficher le classement : {error}")
            return

        if not ranking:
            await ctx.send(
                "Aucun joueur n'est inscrit à cet événement."
            )
            return

        event = self.manager.get_event(event_id)

        embed = discord.Embed(
            title=f"Classement — {event['name']}",
            color=discord.Color.dark_purple(),
        )

        for position, player in enumerate(ranking, start=1):
            user_id = player["user_id"]
            member = ctx.guild.get_member(user_id)

            if member is None:
                try:
                    member = await ctx.guild.fetch_member(user_id)
                    username = member.display_name
                except discord.NotFound:
                    user = self.get_user(user_id)

                    if user is None:
                        try:
                            user = await self.fetch_user(user_id)
                        except discord.NotFound:
                            user = None

                    username = user.name if user else "Utilisateur inconnu"
            else:
                username = member.display_name

            embed.add_field(
                name=f"{position}. {username}",
                value=f"**{player['points']}** points",
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
        try:
            result = await self.resolve_activity(
                ctx,
                activity_id,
                event_id,
                joined_only=True,
                command_name="do",
            )

            if result is None:
                return

            resolved_event_id, _ = result

            outcome = self.activities.claim_command(
                ctx.guild.id,
                resolved_event_id,
                ctx.author.id,
                activity_id,
            )
        except (ValueError, OSError) as error:
            await ctx.send(f"Impossible d'effectuer l'activité : {error}")
            return

        status = outcome["status"]

        if status == "not_joined":
            await ctx.send(
                f"Tu dois d'abord rejoindre l'événement avec "
                f"`*event join {resolved_event_id}`."
            )
        elif status == "completed":
            await ctx.send("Tu as déjà obtenu la récompense de cette activité.")
        elif status == "cooldown":
            remaining = outcome["remaining"]
            hours, remainder = divmod(remaining, 3600)
            minutes = remainder // 60

            await ctx.send(
                f"Tu as déjà utilisé cette commande récemment. "
                f"Réessaie dans {hours} h {minutes} min."
            )
        elif status == "success":
            rewards = outcome["rewards"]
            event = self.manager.get_event(resolved_event_id)
            currency = event.get("currency", "monnaie")

            await ctx.send(
                f"Récompense obtenue ! Tu gagnes "
                f"{rewards.get('points', 0)} points et "
                f"{rewards.get('currency', 0)} {currency}."
            )


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
   