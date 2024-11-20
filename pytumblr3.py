"""
Helpful wrapper class and functions for pytumblr. Based on pytumblr. Should soon be updated to be based on pytumblr2.

Used by a few of my projects, so I keep it up to date.
"""

from datetime import datetime
from pathlib import Path
from typing import Generator, Literal, TypedDict, Union

from pytumblr2 import TumblrRestClient
from pytumblr2.helpers import validate_blogname

class Blog(TypedDict):
    name: str
    active: bool
    # ...and the rest

class Reblog(TypedDict):
    "The final reblog's comment"
    comment: str
    tree_html: str

class _TrailPost(TypedDict):
    id: str

class TrailPost(TypedDict):
    "A post in a post's trail. Has less info."
    blog: Blog
    post: _TrailPost
    is_root_item: bool
    content: str
    content_raw: str

HTML = str

class Post(TypedDict):
    blog_name: str
    blog: Blog
    display_avatar = True

    id: int
    id_string: str
    genesis_post_id: str

    type: Literal['text', 'answer'] # and the rest
    format: str # 'html'?
    is_blocks_post_format: bool # default true
    should_open_in_legacy: bool

    post_url: str
    parent_post_url: str
    short_url: str

    title: str
    summary: str
    question: HTML
    answer: HTML
    body: Union[HTML, None]

    tags: list[str]
    note_count: int
    reblog: Reblog
    trail: TrailPost # ??

    slug: str
    date: str  # not exactly in ISO
    timestamp: int
    state: str # 'published'?

    # Sharing
    can_like: bool
    can_reblog: bool
    interactability_reblog: str
    reblog_key: str
    
    can_send_in_message: bool
    can_reply: bool

    # Muting
    can_mute: bool
    muted: bool
    mute_ent_timestamp: int

    # Don't do this please
    can_blaze: bool
    can_ignite: bool
    is_blazed: bool
    is_blaze_pending: bool
    interactability_blaze: str

    # Methods

    def get_date(self):
        return datetime.strptime(self['date'], '%Y-%m-%d %H:%M:%S %Z')
    
    def get_images(self):
        # TODO: handle videos?
        posts = [self]
        if 'trail' in self:
            posts += self['trail']
        for p in posts:
            for block in p['content']:
                if block['type'] != 'image':
                    continue
                yield {
                    t['width']: t['url']
                    for t in block['media']}

# Convenience methods

def get_srcset(srcset_raw: str):
    if not srcset_raw:
        return {}
    srcset = dict()
    for src in srcset_raw.split(', '):
        url, width = src.split(' ', 1)
        assert width.endswith('w')
        width = int(width[:-1])
        srcset[width] = url
    srcset['max'] = url
    return srcset

class Client(TumblrRestClient):
    """
    pytumblr2's TumblrRestClient with adapted fetching methods.
    
    Register an app with https://www.tumblr.com/oauth/apps.
    See the API console: https://api.tumblr.com/console/calls/user/info
    """

    @classmethod
    def from_keys(cls, path: Path | str):
        """
        If given a path to a .keys file with tokens, starts a client.

        The file should have four lines in the same order
        as the API console returns, that is to say:
        - consumer_key
        - consumer_secret
        - token
        - token_secret
        """
        KEYS = Path(path).read_text().strip().splitlines()
        assert len(KEYS) == 4
        return Client(*KEYS)
    

    @validate_blogname
    def queue_reorder(self, blogname, post_id, insert_after=0):
        """
        Reorders a post in the queue.

        :param blogname: a string, the blogname you want to look up posts
                         for. eg: codingjester.tumblr.com
        :param post_id: an int, the id of the post to move
        :param post_id: which post ID to move it after, or 0 to make it the first post

        :returns: a dict created from the JSON response
        """
        url = "/v2/blog/{}/posts/queue/reorder".format(blogname)
        return self.send_api_request("get", url, {
            post_id: post_id,
            insert_after: insert_after,
        })

    @validate_blogname
    def posts(self, blogname, type=None, **kwargs):
        # modified to add:
        # - after (timestamp)
        
        """
        Gets a list of posts from a particular blog

        :param blogname: a string, the blogname you want to look up posts
                         for. eg: codingjester.tumblr.com
        :param id: an int, the id of the post you are looking for on the blog
        :param tag: a string, the tag you are looking for on posts
        :param limit: an int, the number of results you want
        :param offset: an int, the offset of the posts you want to start at.
        :param after: an int, the timestamp for posts you want after.
        :param before: an int, the timestamp for posts you want before.
        :param filter: the post format you want returned: HTML, text or raw.
        :param type: the type of posts you want returned, e.g. video. If omitted returns all post types.

        :returns: a dict created from the JSON response
        """
        if type is None:
            url = '/v2/blog/{}/posts'.format(blogname)
        else:
            url = '/v2/blog/{}/posts/{}'.format(blogname, type)
        return self.send_api_request("get", url, kwargs, True)

    def get_posts(
            self,
            blogname: str,
            method: Literal['posts', 'queue', 'likes'] = 'posts',
            **kwargs
        ) -> Generator[Post, None, None]:
        """
        Get ALL posts from a blog. Might annoy the API - be wise about it.

        Uses the same kwargs as Client.posts.
        """
        offset = 0

        _get_methods = {
            'posts': lambda **kw: self.posts(blogname, **kw).get('posts', []),
            'queue': lambda **kw: self.queue(blogname, **kw).get('posts', []),
            'likes': lambda **kw: self.likes(**kw).get('liked_posts', [])
        }

        method = _get_methods[method]
        while r := method(limit=50, offset=offset, **kwargs):
            for post in r:
                yield Post(post)
            # yield from r
            offset += 50

    def get_root_post(self, post: Post) -> Post:
        """
        For a post, get the root post of which it is ultimately a reblog chain of.

        May return None in the case that the post is no longer found -
        perhaps the blog deactivated or was banned.
        While reblog posts don't hold all metadata, they do hold its content
        even if this function returns None.
        """

        root = None
        if trail := post['trail']:
            root_ref = trail[0]
            assert root_ref.get('is_root_item', True)
            blog_id = root_ref['blog']['name']
            post_id = root_ref['post']
            result = self.posts(blog_id, id=post_id)

            if len(ps := result.get('posts', [])):
                root = ps[0]
        return root or post