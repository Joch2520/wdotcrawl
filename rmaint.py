import wikidot

# Basic python stuff
import os
import codecs
import pickle as pickle
import json

# git stuff
from git import Repo, Actor
import time # For parsing unix epoch timestamps from wikidot and convert to normal timestamps
import re # For sanitizing usernames to fake email addresses

# Repository builder and maintainer
# Contains logic for actual loading and maintaining the repository over the course of its construction.

# Usage:
#   rm = RepoMaintainer(wikidot, path)
#   rm.buildRevisionList(pages, depth, category, tags)
#   rm.openRepo()
#   while rm.commitNext():
#       pass
#   rm.cleanup()

# Talkative.

class RepoMaintainer:
    def __init__(self, wikidot, path):
        # Settings
        self.wd = wikidot           # Wikidot instance
        self.path = path            # Path to repository
        self.debug = False          # = True to enable more printing
        self.storeRevIds = True     # = True to store .revid with each commit

        # Internal state
        self.wrevs = None           # Compiled wikidot revision list (history)
        self.fetched_revids = []    # Compiled wikidot revision list (history)

        self.rev_no = 0             # Next revision to process
        self.last_names = {}        # Tracks page renames: name atm -> last name in repo
        self.last_parents = {}      # Tracks page parent names: name atm -> last parent in repo
        self.category = None        # Tracks category(s) to get form
        self.tags = None            # Tracks tag(s) to get form

        self.repo = None            # Git repo object
        self.index = None           # Git current index object


    #
    # Saves and loads revision list from file
    #
    def saveWRevs(self):
        fp = open(self.path+'/.wrevs', 'wb')
        pickle.dump(self.wrevs, fp)
        fp.close()

    def loadWRevs(self):
        fp = open(self.path+'/.wrevs', 'rb')
        self.wrevs = pickle.load(fp)
        fp.close()

    def savePages(self, pages):
        fp = open(self.path+'/.pages', 'wb')
        pickle.dump(pages, fp)
        fp.close()

    def appendFetchedRevid(self, revid):
        fp = open(self.path+'/.fetched.txt', 'a')
        fp.write(revid + '\n')
        fp.close()

    def loadFetchedRevids(self):
        self.fetched_revids = [line.rstrip() for line in open(self.path+'/.fetched.txt', 'r')]

    # Persistent metadata about the repo:
    #  - Tracks page renames: name atm -> last name in repo
    #  - Tracks page parent names: name atm -> last parent in repo
    # Variable metadata about the repo:
    #  - Tracks category: settings for category(s) to get from
    #  - Tracks tags: settings for tag(s) to get from
    def saveMetadata(self):
        metadata = { 'category': self.category, 'tags': self.tags, 'names': self.last_names, 'parents': self.last_parents }
        fp = open(self.path+'/.metadata.json', 'w')
        json.dump(metadata, fp)
        fp.close()

    def loadMetadata(self):
        fp = open(self.path+'/.metadata.json', 'r')
        metadata = json.load(fp)
        self.category = metadata['category']
        self.tags = metadata['tags']
        self.last_names = metadata['names']
        self.last_parents = metadata['parents']
        fp.close()

        self.loadFetchedRevids()
    #
    # Compiles a combined revision list for a given set of pages, or all pages on the site.
    #  pages: compile history for these pages
    #  depth: download at most this number of revisions
    #  category: get from these category(s)
    #  tags: get from these tag(s)
    #
    # If there exists a cached revision list at the repository destination,
    # it is loaded and no requests are made.
    #
    def buildRevisionList(self, pages = None, depth = 10000, category = None, tags = None, created_by = None):
        if os.path.isfile(self.path+'/.metadata.json'):
            self.loadMetadata()

        self.category = category if category else (self.category if self.category else '.')
        self.tags = tags if tags else (self.tags if self.tags else None)
        self.created_by = created_by if created_by else (self.created_by if self.created_by else None)

        if os.path.isfile(self.path+'/.wrevs'):
            print("Loading cached revision list...")
            self.loadWRevs()
        else:
            self.wrevs = []
            if self.debug:
                print('No existing wrevs')

        if os.path.isfile(self.path+'/.fetched.txt'):
            self.loadFetchedRevids()
            print(self.fetched_revids)
        else:
            self.fetched_revids = []

        if self.debug:
            print("Building revision list...")

        if not pages:
            if os.path.isfile(self.path+'/.pages'):
                print('Loading fetched pages')
                fp = open(self.path+'/.pages', 'rb')
                pages = pickle.load(fp)
                fp.close()


            if not pages:
                if self.debug:
                    print('Need to fetch pages')
                pages = self.wd.list_pages(10000, self.category, self.tags, self.created_by)
                self.savePages(pages)
            elif self.debug:
                print(len(pages), 'pages loaded')

        fetched_pages = []

        if self.debug:
            print('Collecting already pages we already got revisions for')

        # TODO: I don't know python, but this is highly suboptimal (and takes a ton of time)
        # Should use a set/hashmap/whatever python calls it
        for wrev in self.wrevs:
            page_name = wrev['page_name']

            if page_name in fetched_pages:
                continue

            fetched_pages.append(page_name)

        if self.debug:
            print("Already fetched revisions for " + str(len(fetched_pages)) + " of " + str(len(pages)))

        fetched = 0
        for page in pages:
            if page in fetched_pages:
                continue

            # TODO: more generic blacklisting
            if page == "sandbox":
                if self.debug:
                    print("Skipping", page)
                continue

            if self.debug:
                print("Querying page: " + page + " " + str(fetched) + "/" + str(len(pages) - len(fetched_pages)))
            fetched += 1
            page_id = self.wd.get_page_id(page)

            if self.debug:
                print(("ID: "+str(page_id)))

            if page_id is None:
                print('Page gone?', page)
                continue

            revs = self.wd.get_revisions(page_id, depth)
            print("Revisions to fetch: "+str(len(revs)))
            for rev in revs:
                if rev['id'] in self.fetched_revids:
                    print(rev['id'], 'already fetched')
                    continue

                self.wrevs.append({
                  'page_id' : page_id,
                  'page_name' : page, # name atm, not at revision time
                  'rev_id' : rev['id'],
                  'flag' : rev['flag'],
                  'date' : rev['date'],
                  'user' : rev['user'],
                  'comment' : rev['comment'],
                })
            self.saveWRevs() # Save a cached copy

        print("")

        print(("Total revisions: "+str(len(self.wrevs))))

        if self.debug:
            print("Sorting revisions...")

        self.wrevs.sort(key=lambda rev: rev['date'])

        if self.debug:
            if len(self.wrevs) < 100:
                print("")
                print("Revision list: ")
                for rev in self.wrevs:
                    print((str(rev)+"\n"))
                print("")
            else:
                print("Too many revisions, not printing everything")


    #
    # Saves and loads operational state from file
    #
    def saveState(self):
        fp = open(self.path+'/.wstate', 'wb')
        pickle.dump(self.rev_no, fp)
        fp.close()

    def loadState(self):
        fp = open(self.path+'/.wstate', 'rb')
        self.rev_no = pickle.load(fp)
        fp.close()


    #
    # Initializes the construction process, after the revision list has been compiled.
    # Either creates a new repo, or loads the existing one at the target path
    # and restores its construction state.
    #
    def openRepo(self):
        # Create a new repository or continue from aborted dump
        self.last_names = {} # Tracks page renames: name atm -> last name in repo
        self.last_parents = {} # Tracks page parent names: name atm -> last parent in repo

        if os.path.isfile(self.path+'/.git'):
            print("Continuing from aborted dump state...")
            self.loadState()
            self.repo = Repo(self.path)
            assert not self.repo.bare

        else: # create a new repository (will fail if one exists)
            print("Initializing repository...")
            self.repo = Repo.init(self.path)
            self.rev_no = 0

            if self.storeRevIds:
                # Add revision id file to the new repo
                fname = '/.revid'
                codecs.open(self.path + fname, "w", "UTF-8").close()
                self.repo.index.add([fname])
                self.index.commit("Initial creation of repo")
        self.index = self.repo.index

    #
    # Takes an unprocessed revision from a revision log, fetches its data and commits it.
    # Returns false if no unprocessed revisions remain.
    #
    def commitNext(self):
        if self.rev_no >= len(self.wrevs):
            return False

        rev = self.wrevs[self.rev_no]
        pagerev = [val for idx,val in enumerate(self.wrevs) if (val['page_id']==rev['page_id'])]
        tagrev = [val for idx,val in enumerate(pagerev) if (val['flag']=='A')]
        unixname = rev['page_name']

        if rev['rev_id'] in self.fetched_revids:
            if self.debug:
                print(rev['rev_id'], 'already fetched')

            self.rev_no += 1

            self.saveState() # Update operation state
            return True

        source = self.wd.get_revision_source(rev['rev_id'])
        # Page title and unix_name changes are only available through another request:
        details = self.wd.get_revision_version(rev['rev_id'])
        # Page tags changes are only available through a third request:
        if tagrev:
            new_rev_id = tagrev[0]['rev_id'] if rev['rev_id']!=tagrev[0]['rev_id'] else pagerev[0]['rev_id']
            tags = self.wd.get_tags_from_diff(rev['rev_id'], new_rev_id)
        else:
            # Page scraping for tags
            # This has to be done because we dont know if the page tags are empty or same as created with url /tags/
            tags = self.wd.get_page_tags(unixname)

        # Store revision_id for last commit
        # Without this, empty commits (e.g. file uploads) will be skipped by Git
        if self.storeRevIds:
            fname = self.path+'/.revid'
            outp = codecs.open(fname, "w", "UTF-8")
            outp.write(rev['rev_id']) # rev_ids are unique amongst all pages, and only one page changes in each commit anyway
            outp.close()

        winsafename = unixname.replace(':','~') # windows does not allow ':' in file name, this makes pages with colon in unix name safe on windows
        rev_unixname = details['unixname'] if details['unixname'] else unixname # may be different in revision than atm
        rev_winsafename = rev_unixname.replace(':','~') # windows-safe name in revision

        # Unfortunately, there's no exposed way in Wikidot to see page breadcrumbs at any point in history.
        # The only way to know they were changed is revision comments, though evil people may trick us.
        if rev['comment'].startswith('Parent page set to: "'):
            # This is a parenting revision, remember the new parent
            parent_unixname = rev['comment'][21:-2]
            self.last_parents[unixname] = parent_unixname
        else:
            # Else use last parent_unixname we've recorded
            parent_unixname =  self.last_parents[unixname] if unixname in self.last_parents else None
        # There are also problems when parent page gets renamed -- see updateChildren

        # If the page is tracked and its name just changed, tell Git
        fname = str(rev_winsafename) + '.txt'
        rename = (unixname in self.last_names) and (self.last_names[unixname] != rev_unixname)

        commit_msg = ""

        if rename:
            name_rename_from = str(self.last_names[unixname]).replace(':','~')+'.txt'

            if self.debug:
                print("Moving renamed", name_rename_from, "to", fname)

            self.updateChildren(self.last_names[unixname], rev_unixname) # Update children which reference us -- see comments there

            # Try to do the best we can, these situations usually stem from vandalism people have cleaned up
            if os.path.isfile(self.path + '/' + name_rename_from):
                self.index.move([name_rename_from, fname], force=True)
                commit_msg += "Renamed from " + str(self.last_names[unixname]) + ' to ' + str(rev_unixname) + ' '
            else:
                print("Source file does not exist, probably deleted or renamed from already?", name_rename_from)

        # Add new page
        elif not os.path.isfile(self.path + '/' + fname): # never before seen
            commit_msg += "Created "
            if self.debug:
                print("Adding", fname)
        elif rev['comment'] == '':
            commit_msg += "Updated "

        self.last_names[unixname] = rev_unixname

        # Ouput contents
        outp = codecs.open(self.path + '/' + fname, "w", "UTF-8")
        if details['title']:
            outp.write('title:'+details['title']+'\n')
        if tags:
            outp.write('tags:'+' '.join(tags)+'\n')
        if parent_unixname:
            outp.write('parent:'+parent_unixname+'\n')
        outp.write(source)
        outp.close()

        commit_msg += rev_unixname

        # Commit
        if rev['comment'] != '':
            commit_msg += ': ' + rev['comment']
        else:
            commit_msg += ' (no message)'
        if rev['date']:
            parsed_time = time.gmtime(int(rev['date'])) # TODO: assumes GMT
            commit_date = time.strftime('%Y-%m-%d %H:%M:%S', parsed_time)
        else:
            commit_date = None

        print("Committing: " + str(self.rev_no) + '. '+commit_msg)

        # Include metadata in the commit (if changed)
        self.appendFetchedRevid(rev['rev_id'])
        self.saveMetadata()
        self.index.add([str(fname), '.metadata.json'])

        username = str(rev['user'])
        email = re.sub(pattern = r'[^a-zA-Z0-9\-.+]', repl='', string=username).lower() + '@' + self.wd.sitename
        author = Actor(username, email)

        commit = self.index.commit(commit_msg, author=author, author_date=commit_date)

        if self.debug:
            print('Committed', commit.name_rev, 'by', author)

        self.fetched_revids.append(rev['rev_id'])

        self.rev_no += 1
        self.saveState() # Update operation state

        return True


    #
    # Updates all children of the page to reflect parent's unixname change.
    #
    # Any page may be assigned a parent, which adds entry to revision log. We store this as parent:unixname in the page body.
    # A parent may then be renamed.
    # Wikidot logs no additional changes for child pages, yet they stay linked to the parent.
    #
    # Therefore, on every rename we must update all linked children in the same revision.
    #
    def updateChildren(self, oldunixname, newunixname):
        for child in list(self.last_parents.keys()):
            if self.last_parents[child] == oldunixname:
                self.updateParentField(child, self.last_parents[child], newunixname)

    #
    # Processes a page file and updates "parent:..." string to reflect a change in parent's unixname.
    # The rest of the file is preserved.
    #
    def updateParentField(self, child_unixname, parent_oldunixname, parent_newunixname):
        child_winsafename = child_unixname.replace(':','~')
        parent_winsafename = parent_unixname.replace(':','~')
        with codecs.open(self.path+'/'+child_winsafename+'.txt', "r", "UTF-8") as f:
            content = f.readlines()
        # Since this is all tracked by us, we KNOW there's a line in standard format somewhere
        idx = content.index('parent:'+parent_oldunixname+'\n')
        if idx < 0:
            raise Exception("Cannot update child page "+child_unixname+": "
                +"it is expected to have parent set to "+parent_oldunixname+", but there seems to be no such record in it.");
        content[idx] = 'parent:'+parent_newunixname+'\n'
        with codecs.open(self.path+'/'+child_winsafename+'.txt', "w", "UTF-8") as f:
            f.writelines(content)


    #
    # Finalizes the construction process and deletes any temporary files.
    #
    def cleanup(self):
        if os.path.exists(self.path+'/.wstate'):
            os.remove(self.path+'/.wstate')
        else:
            print("wstate does not exist?")

        if os.path.exists(self.path+'/.wrevs'):
            os.remove(self.path+'/.wrevs')
        else:
            print("wrevs does not exist?")

        if os.path.exists(self.path+'/.pages'):
            os.remove(self.path+'/.pages')

        if self.rev_no > 0:
            self.index.add(['.fetched.txt'])
            self.index.commit('Updating fetched revisions')
