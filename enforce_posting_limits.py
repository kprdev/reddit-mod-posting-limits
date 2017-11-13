#!/usr/bin/python
import sys
import time
import logging
import praw
import prawcore
from pprint import pprint

# Set to True to test, posts won't be removed
POST_TEST_MODE = False

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
    
    logging.info('Watching subreddit: %s', subreddit_name)
    logging.info('Current limit set to %d posts in %d hours',
                 post_limit_count, post_limit_hours)

    reddit = praw.Reddit(user_agent=user_agent,
                         client_id=client_id,
                         client_secret=client_secret,
                         username=username,
                         password=password)
    subreddit = reddit.subreddit(subreddit_name)
    check_subreddit(subreddit, post_limit_count, post_limit_hours)


def check_subreddit(subreddit, post_limit_count, post_limit_hours):
    max_new_submissions = 25
    loop_delay = 119 # seconds
    
    # Initial search range will start 10m ago.
    search_time = time.time() - (60*10)

    # The loop
    running = True
    while running:
        while True:
            try:
                submissions = subreddit.new(limit=max_new_submissions)
                new_submissions = []
                for submission in submissions:
                    # Window to give the cache a chance to update.
                    caching_window = 45
                    # New submissions will come in newest first.
                    # Save the ones newer than last_new_post_time.
                    if submission.created_utc > search_time:
                        new_submissions.append(submission)
                break
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

        logging.debug("New submission count is %d", len(new_submissions))
        
        if len(new_submissions) > 0:
            new_submissions.reverse()
            # Now they should be oldest first.
            for submission in new_submissions:
                stamp = time.strftime("%a, %d %b %Y %H:%M:%S %Z",
                                      time.gmtime(submission.created_utc))
                link = 'https://redd.it' + submission.id
                logging.info('New post: %s, "%s" by "%s", %s', stamp,
                             submission.title, submission.author.name, link)
                
                try:
                    check_post_limits(subreddit, submission, post_limit_hours,
                                      post_limit_count)
                except praw.exceptions.APIException as e:
                    logging.error('API Exception!')
                    pprint(vars(e))
                    break
                else:
                    search_time = submission.created_utc
        else:
            search_time = time.time()

        try:
            time.sleep(loop_delay)
        except KeyboardInterrupt:
            print ('..exiting')
            sys.exit(0)


def check_post_limits(subreddit, submission, limit_hours, limit_posts):
    # provide a small window for less strict checking
    buffer_seconds = 600
    
    start_time = submission.created_utc - (limit_hours * 60 * 60) + buffer_seconds
    # Exclude the current post from the range check since reddit sometimes
    # doesn't include it (cache?). We will add it in manually later.
    stop_time = submission.created_utc - 1
    username = submission.author.name
    
    params = "author:'" + username + "'"
    while True:
        try:
            user_submissions = list(subreddit.submissions(start_time, stop_time, params))
            break
        except Exception as e:
            print (e)
            time.sleep(60)
            
    count = len(user_submissions)
    for i, user_submission in enumerate(user_submissions, start=1):
        stamp = time.strftime("%Y-%m-%d %H:%M:%S %Z",
                              time.gmtime(user_submission.created_utc))
        link = 'https://redd.it/' + user_submission.id
        logging.info('Old post: %s, (%d/%d) "%s", %s', stamp, i, count,
                     user_submission.title, link)
    
    # Include the post excluded earlier
    count += 1
    logging.info('%d hour post count: %d', limit_hours, count)
    
    if count > limit_posts and not POST_TEST_MODE:
        try:
            submission.mod.remove()
        except Exception as e:
            # If the login user isn't permitted to remove posts, don't stop
            if e.response.status_code == 403:
                logging.error('The current username does not have permission '
                              'to remove submissions! Verify the login '
                              'is correct and has subreddit mod access.')
            else:
                raise e
        else:
            logging.info('"%s" removed.', submission.title)
            msg_link = "/message/compose/?to=/" + subreddit._path
            reply_text = (
                "Your submission was automatically removed because you have "
                "exceeded **{}** submissions within the last **{}** hours.\n\n"
                "*I am a bot, and this action was performed automatically. "
                "Please [contact the moderators of this subreddit]"
                "(" + msg_link + ") if you have questions or "
                "concerns.*").format(limit_posts, limit_hours)
            submission.reply(reply_text)


if __name__ == '__main__':
    main()
