import discord
import logging
import sys
from datetime import datetime
from typing import List
from sqlalchemy.orm.collections import InstrumentedList

# Function overloading
from multipledispatch import dispatch

from bot.utils.db_utils import DBUtil

from bot.config.logging_config import log_handler, console_handler
from bot.config.schemas import Proposals, Voters, FinanceRecipients
from bot.config.const import DEFAULT_LOG_LEVEL, Vote

logger = logging.getLogger(__name__)
logger.setLevel(DEFAULT_LOG_LEVEL)
logger.addHandler(log_handler)
logger.addHandler(console_handler)

db = DBUtil()

proposals = {}


def find_matching_voter(user_id, voting_message_id):
    """
    Returns either a single Voter object that matches the provided user_id and voting_message_id, or a list of Voter objects that match, which is usually empty but may contain multiple objects if there's an error in the system.
    """
    voters_found = []
    # Iterate through proposals and check for voters with matching ids
    for id in proposals:
        p = proposals[id]
        for v in p.voters:
            if v.user_id == user_id and v.voting_message_id == voting_message_id:
                voters_found.append(v)
    # If a single match is found, return it
    if len(voters_found) == 1:
        return voters_found[0]
    # Otherwise return the entire array (it should be empty most of the time, the case when there's
    # more than 1 match is erroneous, but may happen and should be handled accordingly)
    else:
        return voters_found


def get_voters_with_vote(proposal, vote: Vote):
    """
    Returns an array of proposal voters with a certain voting value (e.g. "yes" or "no).
    """
    voters = []
    for voter in proposal.voters:
        if int(voter.value) == vote.value:
            voters.append(voter)
    return voters


async def add_voter(proposal, voter):
    await db.add(voter)
    await db.append(proposal.voters, voter)


async def remove_voter(proposal, voter):
    await db.remove(proposal.voters, voter)
    await db.delete(voter)


def is_relevant_proposal(voting_message_id):
    if not isinstance(voting_message_id, int):
        raise ValueError(
            f"voting_message_id should be an int, got {type(voting_message_id)} instead: {voting_message_id}"
        )
    return voting_message_id in proposals


def get_proposals_count():
    return len(proposals)


def get_proposal(voting_message_id):
    if voting_message_id in proposals:
        return proposals[voting_message_id]
    else:
        logger.critical(
            f"Unable to get the proposal {voting_message_id} - it couldn't be found in the list of active proposals."
        )
        raise ValueError(f"Invalid proposal ID: {voting_message_id}")


def get_proposal_initiated_by(message_id):
    """
    Returns a proposal that was either initiated by a message with the given id, or the bot has replied with a message of given id to the initial proposer message (bot_response_message_id).Use case: to cover users who have reacted to a wrong message (this is helpful during onboarding).
    """
    if not proposals:
        return None
    for proposal in proposals.values():
        if proposal.message_id == message_id or proposal.bot_response_message_id == message_id:
            return proposal
    return None


async def remove_proposal(voting_message_id, db: DBUtil):
    if voting_message_id in proposals:
        logger.info("Removing data: %s", proposals[voting_message_id])
        # Removing from DB; the delete-orphan cascade will clean up the Voters table with the associated data
        await db.delete(proposals[voting_message_id])
        # Removing from dict
        del proposals[voting_message_id]
    else:
        logger.critical(
            f"Unable to remove the proposal {voting_message_id} - it couldn't be found in the list of active proposals."
        )
        raise ValueError(f"Invalid proposal ID: {voting_message_id}")


def validate_grantless_proposal(new_proposal):
    # Some extra validation; it's helpful when the values of the ORM object were changed after it was created, and for debugging as it provides detailed error messages
    if not isinstance(new_proposal.message_id, int):
        raise ValueError(
            f"message_id should be an int, got {type(new_proposal.message_id)} instead: {new_proposal.message_id}"
        )
    if not isinstance(new_proposal.channel_id, int):
        raise ValueError(
            f"channel_id should be an int, got {type(new_proposal.channel_id)} instead: {new_proposal.channel_id}"
        )
    if not isinstance(new_proposal.author_id, (discord.User, str, int)):
        raise ValueError(
            f"author should be discord.User or str or int, got {type(new_proposal.author_id)} instead: {new_proposal.author_id}"
        )
    if not isinstance(new_proposal.voting_message_id, int):
        raise ValueError(
            f"voting_message_id should be an int, got {type(new_proposal.voting_message_id)} instead: {new_proposal.voting_message_id}"
        )
    if not isinstance(new_proposal.description, str):
        raise ValueError(
            f"description should be a string, got {type(new_proposal.description)} instead: {new_proposal.description}"
        )
    if not isinstance(new_proposal.not_financial, bool):
        raise ValueError(
            f"not_financial should be bool, got {type(new_proposal.not_financial)} instead: {new_proposal.not_financial}"
        )
    if not isinstance(new_proposal.submitted_at, datetime):
        raise ValueError(
            f"submitted_at should be datetime, got {type(new_proposal.submitted_at)} instead: {new_proposal.submitted_at}"
        )
    if not isinstance(new_proposal.closed_at, datetime):
        raise ValueError(
            f"closed_at should be datetime, got {type(new_proposal.closed_at)} instead: {new_proposal.closed_at}"
        )
    if not isinstance(new_proposal.bot_response_message_id, int):
        raise ValueError(
            f"bot_response_message_id should be an int, got {type(new_proposal.bot_response_message_id)} instead: {new_proposal.bot_response_message_id}"
        )
    if not isinstance(new_proposal.threshold_negative, int):
        raise ValueError(
            f"threshold should be an int, got {type(new_proposal.threshold_negative)} instead: {new_proposal.threshold_negative}"
        )


def validate_proposal_with_grant(new_grant_proposal):
    # The validation of proposals with grant is the same as with grantless, with a couple of extra fields
    validate_grantless_proposal(new_grant_proposal)

    if not isinstance(new_grant_proposal.finance_recipients, InstrumentedList):
        raise ValueError(
            f"finance_recipients should be InstrumentedList, got {type(new_grant_proposal.finance_recipients)} instead: {new_grant_proposal.finance_recipients}"
        )


@dispatch(Proposals)
def add_proposal(new_proposal):
    """
    Add a new grant proposal to the database and to a dictionary.
    Parameters:
    new_proposal (Proposals): The new grant proposal object to be added.
    db (optional): The DBUtil object used to save a proposal. If this parameter is not specified,proposal will only be added to in-memory dict (use case: when restoring data from DB).
    """

    if new_proposal.not_financial:
        validate_grantless_proposal(new_proposal)
    else:
        validate_proposal_with_grant(new_proposal)

    # Adding to dict
    proposals[new_proposal.voting_message_id] = new_proposal
    logger.info("Added proposal with voting_message_id=%s", new_proposal.voting_message_id)


@dispatch(Proposals, DBUtil)
async def add_proposal(new_proposal, db):
    """
    Overloaded add_proposal that also saves to DB, with one extra parameter - the DBUtil object used to save a proposal.
    """
    # Add to dict
    add_proposal(new_proposal)
    # Add to DB
    if db:
        await db.add(new_proposal)
        logger.info("Inserted proposal into DB: %s", new_proposal)
    else:
        raise Exception("Incorrect DB identifier was given.")
