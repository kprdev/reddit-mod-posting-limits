#!/usr/bin/python
import sys
import time
import logging
import praw
import prawcore
from pprint import pprint

submission_pool = []

# Set to True to test, posts won't be removed
POST_TEST_MODE = False
# Set to a discord webhook for announcements
DISCORD_WEBHOOK_URL = None

def main():
    # SET THESE - reddit application configuration
    user_agent = ''
    client_id = ''
    client_secret = ''
    username = ''
    password = ''
    
    # SET THESE - Customize these for your subreddit.
    subreddit_name = ''
    post_limit_count = 4
    post_limit_hours = 24
    
    logging.basicConfig(
        format='%(asctime)s %(levelname)s %(message)s',
        level=logging.INFO
    )
    
    reddit = praw.Reddit(user_agent=user_agent,
                         client_id=client_id,
                         client_secret=client_secret,
                         username=username,
                         password=password)
    
    logging.info('Watching subreddit: %s', subreddit_name)
    logging.info('Current limit set to %d posts in %d hours',
                 post_limit_count, post_limit_hours)
    
    subreddit = reddit.subreddit(subreddit_name)
    check_subreddit(subreddit, post_limit_count, post_limit_hours)


def filter_submissions(submissions, start_time, end_time = None, username = None):
    """Return all submissions created after the start_time.
        Optional: Also before end_time if given.
        Optional: Also by username if given."""
    filtered = []
    for s in submissions:
        if end_time and s.created_utc >= end_time:
            continue
        elif username and username != s.author.name:
            continue
        elif s.created_utc > start_time:
            filtered.append(s)
    return filtered


def check_subreddit(subreddit, post_limit_count, post_limit_hours):
    global submission_pool
    max_new_submissions = 100
    loop_delay = 119 # seconds
    
    # Initial search range will start 10m ago.
    #search_time = time.time() - (60*60*6)

    # The loop
    running = True
    dotter = Dotter(120)
    while running:
        while True:
            submission_pool = []
            try:
                submissions = subreddit.new(limit=max_new_submissions)
            except praw.exceptions.APIException as e:
                logging.error('API Exception!')
                pprint(vars(e))
                logging.info('Retrying in 60 seconds.')
                time.sleep(60)
            except praw.exceptions.ClientException as e:
                logging.error('Client Exception!')
                pprint(vars(e))
                logging.info('Retrying in 60 seconds.')
                time.sleep(60)
            except prawcore.exceptions.OAuthException as e:
                logging.critical('Login failed.')
                sys.exit(1)
            except Exception as e:
                pprint(vars(e))
                time.sleep(120)
            else:
                for s in submissions:
                    submission_pool.append(s)
                if search_time:
                    new_submissions = filter_submissions(submission_pool, search_time)
                else:
                    new_submissions = [ submission_pool[0] ]
                    search_time = submission_pool[0].created_utc
                # These start newest first. We want oldest first
                new_submissions.reverse()
                break

        if len(new_submissions) > 0:
            dotter.reset()
            stamp = time.strftime("%Y-%m-%d %H:%M:%S %Z",
                                  time.localtime(search_time))
            logging.info("- New submission count is %d since %s", len(new_submissions),
                        stamp)

            for submission in new_submissions:
                # Announce to discord
                send_discord_webhook(submission)

                stamp = time.strftime("%Y-%m-%d %H:%M:%S %Z",
                                      time.localtime(submission.created_utc))
                link = 'https://redd.it/' + submission.id
                logging.info('-- New post: %s, "%s" by "%s", %s', stamp,
                             submission.title, submission.author.name, link)
                
                try:
                    check_post_limits(submission, post_limit_hours,
                                      post_limit_count)
                except praw.exceptions.APIException as e:
                    logging.error('API Exception!')
                    pprint(vars(e))
                    break
                else:
                    search_time = submission.created_utc
        else:
            #search_time = time.time()
            dotter.dot()

        try:
            time.sleep(loop_delay)
        except KeyboardInterrupt:
            print ('..exiting')
            sys.exit(0)


def check_post_limits(orig_submission, limit_hours, limit_posts):
    buffer_seconds = 600
    start_time = (orig_submission.created_utc 
                   - (limit_hours * 60 * 60) 
                   + buffer_seconds)
    username = orig_submission.author.name
    subreddit = orig_submission.subreddit
    
    search_submissions = filter_submissions(submission_pool, start_time,
        orig_submission.created_utc, username)
    
    count = len(search_submissions)
    for i, s in enumerate(search_submissions, 1):
        stamp = time.strftime("%Y-%m-%d %H:%M:%S %Z",
                              time.localtime(s.created_utc))
        link = 'https://redd.it/' + s.id
        logging.info('Post history (%d/%d): %s, "%s", %s', i, count, stamp,
                     s.title, link)
    
    # Include the excluded post
    count += 1
    logging.info('%d hour post count: %d', limit_hours, count)
    
    if count > limit_posts and POST_TEST_MODE:
        logging.info('Test mode is ON. Post not removed.')
    elif count > limit_posts and not POST_TEST_MODE:
        try:
            orig_submission.mod.remove()
        except Exception as e:
            # If the login user isn't permitted to remove posts, don't stop
            if e.response.status_code == 403:
                logging.error('The current username does not have permission '
                              'to remove submissions! Verify the login '
                              'is correct and has subreddit mod access.')
            else:
                raise e
        else:
            name = "u/" + orig_submission.author.name
            logging.info('"%s" removed.', orig_submission.title)
            msg_link = "/message/compose/?to=/" + subreddit._path
            reply_text = (
                "Hi " + name + ",\n\n"
                "Your submission was automatically removed because you have "
                "exceeded **{}** submissions within the last **{}** hours.\n\n"
                "*I am a bot, and this action was performed automatically. "
                "Please [contact the moderators of this subreddit]"
                "(" + msg_link + ") if you have questions or "
                "concerns.*").format(limit_posts, limit_hours)
            notification = orig_submission.reply(reply_text)
            notification.mod.distinguish('yes')


def send_discord_webhook(submission):
    if not DISCORD_WEBHOOK_URL:
        return
    
    import json
    import requests

    stamp = time.strftime("%Y-%m-%dT%H:%M:%SZ",
                          time.gmtime(submission.created_utc))
    author = '[{}](https://www.reddit.com/u/{})'.format(submission.author.name,
        submission.author.name)
    data = {'embeds':
                [{
                    'title': submission.title,
                    'url': 'https://www.reddit.com'+submission.permalink,
                    'timestamp': stamp,
                    'fields': [
                        {
                            'name': 'Author',
                            'value': author,
                            'inline': 'true'
                        },
                        {
                            'name': 'Image URL',
                            'value': submission.url,
                            'inline': 'true'
                        }
                    ],
                    'image': {
                        'url': submission.url
                    }
                }]
            }

    while True:
        response = requests.post(
            DISCORD_WEBHOOK_URL, data=json.dumps(data),
            headers = {'Content-Type': 'application/json'}
        )
        if response.status_code != 204:
            logging.error('Request to discord returned error %s, response is: %s'
                % (response.status_code, response.text))
            time.sleep(10)
            continue
        break


class Dotter:
    """Show time passing with easy to read symbols."""
    def __init__(self, seconds = 120):
        self.count = 0
        self.seconds_per_dot = seconds

    def reset(self):
        if self.count > 0:
            self.count = 0
            print('')

    def dot(self):
        self.count = self.count + 1
        minutes = self.count * self.seconds_per_dot / 60
        if minutes % 60 == 0:
            sys.stdout.write('^')
        elif minutes % 30 == 0:
            sys.stdout.write('!')
        elif minutes % 15 == 0:
            sys.stdout.write('+')
        elif minutes % 10 == 0:
            sys.stdout.write(':')
        else:
            sys.stdout.write('.')
        sys.stdout.flush()


if __name__ == '__main__':
    main()
