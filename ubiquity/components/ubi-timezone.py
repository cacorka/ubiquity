# -*- coding: utf-8; Mode: Python; indent-tabs-mode: nil; tab-width: 4 -*-

# Copyright (C) 2006, 2007, 2008 Canonical Ltd.
# Written by Colin Watson <cjwatson@ubuntu.com>.
#
# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 2 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program; if not, write to the Free Software
# Foundation, Inc., 51 Franklin St, Fifth Floor, Boston, MA  02110-1301  USA

import os
import time
import re

import debconf
import PyICU

from ubiquity.plugin import *
from ubiquity import i18n
import ubiquity.tz

NAME = 'timezone'
AFTER = 'language'
WEIGHT = 10

class PageGtk(PluginUI):
    def __init__(self, controller, *args, **kwargs):
        self.controller = controller
        try:
            import gtk
            builder = gtk.Builder()
            self.controller.add_builder(builder)
            builder.add_from_file('/usr/share/ubiquity/gtk/stepLocation.ui')
            builder.connect_signals(self)
            self.page = builder.get_object('stepLocation')
            self.region_combo = builder.get_object('timezone_zone_combo')
            self.city_combo = builder.get_object('timezone_city_combo')
            self.map_window = builder.get_object('timezone_map_window')
            self.setup_page()
        except Exception, e:
            self.debug('Could not create timezone page: %s', e)
            self.page = None
        self.plugin_widgets = self.page

    def plugin_translate(self, lang):
        c = self.controller
        if c.get_string('ubiquity/imported/time-format', lang) == '12-hour':
            fmt = c.get_string('ubiquity/imported/12-hour', lang)
        else:
            fmt = c.get_string('ubiquity/imported/24-hour', lang)
        self.tzmap.set_time_format(fmt)

    def set_timezone(self, timezone):
        self.fill_timezone_boxes()
        self.select_city(None, timezone)

    def get_timezone(self):
        i = self.city_combo.get_active()
        m = self.city_combo.get_model()
        return m[i][1]

    @only_this_page
    def fill_timezone_boxes(self):
        m = self.region_combo.get_model()
        tz = self.controller.dbfilter

        # Regions are a translated shortlist of regions, followed by full list
        m.clear()
        lang = os.environ['LANG'].split('_', 1)[0]
        region_pairs = tz.build_shortlist_region_pairs(lang)
        if region_pairs:
            for pair in region_pairs:
                m.append(pair)
            m.append([None, None, None])
        region_pairs = tz.build_region_pairs()
        for pair in region_pairs:
            m.append(pair)

    @only_this_page
    def select_country(self, country):
        def country_is_in_region(country, region):
            if not region: return False
            return country in self.controller.dbfilter.get_countries_for_region(region)

        m = self.region_combo.get_model()
        iterator = self.region_combo.get_active_iter()
        got_country = False
        if iterator:
            got_country = m[iterator][1] == country or \
                          country_is_in_region(country, m[iterator][2])
        if not got_country:
            iterator = m.get_iter_first()
            while iterator:
                if m[iterator][0] is not None and \
                   m[iterator][1] == country or \
                   country_is_in_region(country, m[iterator][2]):
                    self.region_combo.set_active_iter(iterator)
                    break
                iterator = m.iter_next(iterator)

    def select_city(self, unused_widget, city):
        loc = self.tzdb.get_loc(city)
        if not loc:
            return

        self.select_country(loc.country)

        m = self.city_combo.get_model()
        iterator = m.get_iter_first()
        while iterator:
            if m[iterator][1] == city:
                self.city_combo.set_active_iter(iterator)
                return
            iterator = m.iter_next(iterator)
        # We don't have a timezone selection, so don't let the user proceed.
        self.controller.allow_go_forward(False)

    def setup_page(self):
        import gobject, gtk
        from ubiquity import timezone_map
        self.tzdb = ubiquity.tz.Database()
        self.tzmap = timezone_map.TimezoneMap(self.tzdb, '/usr/share/ubiquity/pixmaps/timezone')
        self.tzmap.connect('city-selected', self.select_city)
        self.map_window.add(self.tzmap)
        self.tzmap.show()

        def is_separator(m, i):
            return m[i][0] is None

        self.timeout_id = 0

        # Don't hit on_entry_changed for every key press.
        def queue_entry_changed(e, widget):
            self.controller.allow_go_forward(False)
            if self.timeout_id:
                gobject.source_remove(self.timeout_id)
            self.timeout_id = gobject.timeout_add(300, on_entry_changed, e, widget)

        def on_entry_changed(e, widget):
            text = e.get_text().lower()
            if not text:
                self.controller.allow_go_forward(False)
                return
            m = widget.get_model()
            iterator = m.get_iter_first()
            while iterator:
                country = m.get_value(iterator,0)
                if country is not None:
                    country = country.lower()
                    if text == country or country.find('(%s)' % text) != -1:
                        widget.set_active_iter(iterator)
                        self.controller.allow_go_forward(True)
                        return
                iterator = m.iter_next(iterator)
            self.controller.allow_go_forward(False)

        renderer = gtk.CellRendererText()
        self.region_combo.pack_start(renderer, True)
        self.region_combo.set_text_column(0)
        list_store = gtk.ListStore(gobject.TYPE_STRING, gobject.TYPE_STRING, gobject.TYPE_STRING)
        self.region_combo.set_model(list_store)
        self.region_combo.set_row_separator_func(is_separator)

        completion = gtk.EntryCompletion()
        entry = self.region_combo.child
        entry.connect('changed', queue_entry_changed, self.region_combo)
        entry.set_completion(completion)
        completion.set_model(list_store)
        completion.set_text_column(0)
        completion.set_inline_completion(True)
        completion.set_inline_selection(True)

        renderer = gtk.CellRendererText()
        self.city_combo.pack_start(renderer, True)
        self.city_combo.set_text_column(0)
        city_store = gtk.ListStore(gobject.TYPE_STRING, gobject.TYPE_STRING)
        self.city_combo.set_model(city_store)

        completion = gtk.EntryCompletion()
        entry = self.city_combo.child
        entry.set_completion(completion)
        entry.connect('changed', queue_entry_changed, self.city_combo)
        completion.set_model(city_store)
        completion.set_text_column(0)
        completion.set_inline_completion(True)
        completion.set_inline_selection(True)

        def match_func(completion, key, iter):
            m = completion.get_model()
            text = m.get_value(iter, 0)
            if not text:
                return False
            text = text.lower()
            key = key.lower()
            if text.startswith(key) or text.find('(' + key) != -1:
                return True
            else:
                return False

        completion.set_match_func(match_func)

    @only_this_page
    def on_region_combo_changed(self, *args):
        i = self.region_combo.get_active()
        m = self.region_combo.get_model()
        if i is None or i < 0:
            return
        if m[i][1]:
            countries = [m[i][1]]
        else:
            countries = self.controller.dbfilter.get_countries_for_region(m[i][2])

        m = self.city_combo.get_model()
        m.clear()

        shortlist, longlist = self.controller.dbfilter.build_timezone_pairs(countries)
        for pair in shortlist:
            m.append(pair)
        if shortlist:
            m.append([None, None])
        for pair in longlist:
            m.append(pair)

        default = len(countries) == 1 and self.controller.dbfilter.get_default_for_region(countries[0])
        if default:
            self.select_city(None, default)
        else:
            self.city_combo.set_active_iter(m.get_iter_first())

    def on_city_combo_changed(self, *args):
        i = self.city_combo.get_active()
        if i < 0:
            # There's no selection yet.
            return

        zone = self.get_timezone()
        self.tzmap.select_city(zone)
        self.controller.allow_go_forward(True)

class PageKde(PluginUI):
    plugin_breadcrumb = 'ubiquity/text/breadcrumb_timezone'

    def __init__(self, controller, *args, **kwargs):
        self.controller = controller
        try:
            from PyQt4 import uic
            from ubiquity.frontend.kde_components.Timezone import TimezoneMap

            self.page = uic.loadUi('/usr/share/ubiquity/qt/stepLocation.ui')
            self.tzmap = TimezoneMap(self.page.map_frame)
            self.page.map_frame.layout().addWidget(self.tzmap)

            self.tzmap.zoneChanged.connect(self.mapZoneChanged)
            self.page.timezone_zone_combo.currentIndexChanged[int].connect(self.regionChanged)
            self.page.timezone_city_combo.currentIndexChanged[int].connect(self.cityChanged)
        except Exception, e:
            self.debug('Could not create timezone page: %s', e)
            self.page = None

        self.plugin_widgets = self.page

    @only_this_page
    def refresh_timezones(self):
        lang = os.environ['LANG'].split('_', 1)[0]
        shortlist = self.controller.dbfilter.build_shortlist_region_pairs(lang)
        longlist = self.controller.dbfilter.build_region_pairs()

        self.page.timezone_zone_combo.clear()
        for pair in shortlist:
            self.page.timezone_zone_combo.addItem(pair[0], pair[1])
        self.page.timezone_zone_combo.insertSeparator(self.page.timezone_zone_combo.count())
        for pair in longlist:
            self.page.timezone_zone_combo.addItem(pair[0], pair[2])

    @only_this_page
    def populateCities(self, regionIndex):
        self.page.timezone_city_combo.clear()

        code = str(self.page.timezone_zone_combo.itemData(regionIndex).toPyObject())
        countries = self.controller.dbfilter.get_countries_for_region(code)
        if not countries: # must have been a country code itself
            countries = [code]

        shortlist, longlist = self.controller.dbfilter.build_timezone_pairs(countries)

        for pair in shortlist:
            self.page.timezone_city_combo.addItem(pair[0], pair[1])
        if shortlist:
            self.page.timezone_city_combo.insertSeparator(self.page.timezone_city_combo.count())
        for pair in longlist:
            self.page.timezone_city_combo.addItem(pair[0], pair[1])

        return len(countries) == 1 and self.controller.dbfilter.get_default_for_region(countries[0])

    # called when the region(zone) combo changes
    @only_this_page
    def regionChanged(self, regionIndex):
        if self.controller.dbfilter is None:
            return

        self.page.timezone_city_combo.blockSignals(True)
        #self.page.timezone_city_combo.currentIndexChanged[int].disconnect(self.cityChanged)
        default = self.populateCities(regionIndex)
        self.page.timezone_city_combo.blockSignals(False)
        #self.page.timezone_city_combo.currentIndexChanged[int].connect(self.cityChanged)

        if default:
            self.tzmap.set_timezone(default)
        else:
            self.cityChanged(0)

    # called when the city combo changes
    def cityChanged(self, cityindex):
        zone = str(self.page.timezone_city_combo.itemData(cityindex).toPyObject())
        self.tzmap.zoneChanged.disconnect(self.mapZoneChanged)
        self.tzmap.set_timezone(zone)
        self.tzmap.zoneChanged.connect(self.mapZoneChanged)

    @only_this_page
    def mapZoneChanged(self, loc, zone):
        self.page.timezone_zone_combo.blockSignals(True)
        self.page.timezone_city_combo.blockSignals(True)

        for i in range(self.page.timezone_zone_combo.count()):
            code = str(self.page.timezone_zone_combo.itemData(i).toPyObject())
            countries = self.controller.dbfilter.get_countries_for_region(code)
            if not countries: # must have been a country code itself
                countries = [code]
            if loc.country in countries:
                self.page.timezone_zone_combo.setCurrentIndex(i)
                self.populateCities(i)
                break

        for i in range(self.page.timezone_city_combo.count()):
            code = str(self.page.timezone_city_combo.itemData(i).toPyObject())
            if zone == code:
                self.page.timezone_city_combo.setCurrentIndex(i)
                self.cityChanged(i)
                break

        self.page.timezone_zone_combo.blockSignals(False)
        self.page.timezone_city_combo.blockSignals(False)

    def set_timezone (self, timezone):
        self.refresh_timezones()
        self.tzmap.set_timezone(timezone)

    def get_timezone (self):
        return self.tzmap.get_timezone()

class PageDebconf(PluginUI):
    plugin_title = 'ubiquity/text/timezone_heading_label'

class PageNoninteractive(PluginUI):
    def set_timezone(self, timezone):
        """Set the current selected timezone."""
        self.timezone = timezone

    def get_timezone(self):
        """Get the current selected timezone."""
        return self.timezone

class Page(Plugin):
    def prepare(self, unfiltered=False):
        clock_script = '/usr/share/ubiquity/clock-setup'
        env = {'PATH': '/usr/share/ubiquity:' + os.environ['PATH']}

        if unfiltered:
            # In unfiltered mode, localechooser is responsible for selecting
            # the country, so there's no need to repeat the job here.
            env['TZSETUP_NO_LOCALECHOOSER'] = '1'
            return ([clock_script], ['CAPB', 'PROGRESS'], env)

        self.timezones = []
        self.regions = {}
        self.tzdb = ubiquity.tz.Database()
        self.multiple = False
        try:
            # Strip .UTF-8 from locale, PyICU doesn't parse it
            locale = os.environ['LANG'].rsplit('.', 1)[0]
            self.collator = PyICU.Collator.createInstance(PyICU.Locale(locale))
        except:
            self.collator = None
        if not 'UBIQUITY_AUTOMATIC' in os.environ:
            self.db.fset('time/zone', 'seen', 'false')
            cc = self.db.get('debian-installer/country')
            try:
                self.db.get('tzsetup/country/%s' % cc)
                # ... and if that succeeded:
                self.multiple = True
            except debconf.DebconfError:
                pass
        self.preseed('tzsetup/selected', 'false')
        questions = ['^time/zone$', '^tzsetup/detected$', 'CAPB', 'PROGRESS']
        return ([clock_script], questions, env)

    def capb(self, capabilities):
        self.frontend.debconf_progress_cancellable(
            'progresscancel' in capabilities)

    def run(self, priority, question):
        if question == 'tzsetup/detected':
            zone = self.db.get('time/zone')
            self.ui.set_timezone(zone)
        elif question == 'time/zone':
            if self.multiple:
                # Work around a debconf bug: REGISTER does not appear to
                # give a newly-registered question the same default as the
                # question associated with its template, unless we also
                # RESET it.
                self.db.reset(question)
            zone = self.db.get(question)
            # Some countries don't have a default zone, so just pick the
            # first choice in the list.
            if not zone:
                choices_c = self.choices_untranslated(question)
                if choices_c:
                    zone = choices_c[0]
            self.ui.set_timezone(zone)

        return Plugin.run(self, priority, question)

    def get_default_for_region(self, region):
        try:
            return self.db.get('tzsetup/country/%s' % region)
        except debconf.DebconfError:
            return None

    def collation_key(self, s):
        if self.collator:
            try:
                return self.collator.getCollationKey(s[0]).getByteArray()
            except:
                pass
        return s[0]

    def get_countries_for_region(self, region):
        if region in self.regions: return self.regions[region]

        try:
            codes = self.choices_untranslated('localechooser/countrylist/%s' % region)
        except debconf.DebconfError:
            codes = []
        self.regions[region] = codes
        return codes

    # Returns [('translated country name', None, 'region code')...] list
    def build_region_pairs(self):
        continents = self.choices_display_map('localechooser/continentlist')
        names, codes = zip(*continents.items())
        codes = [c.replace(' ', '_') for c in codes]

        nones = [None for _ in continents]
        pairs = zip(names, nones, codes)
        pairs.sort(key=self.collation_key)
        return pairs

    # Returns [('translated short list of countries', 'timezone')...] list
    def build_shortlist_region_pairs(self, language_code):
        try:
            shortlist = self.choices_display_map('localechooser/shortlist/%s' % language_code)
            # Remove any 'other' entry
            for pair in shortlist.items():
                if pair[1] == 'other':
                    del shortlist[pair[0]]
                    break
            names, codes = zip(*shortlist.items())
            nones = [None for _ in names]
            shortlist = zip(names, codes, nones)
            shortlist.sort(key=self.collation_key)
            return shortlist
        except debconf.DebconfError:
            return []

    # Returns (shortlist, longlist)
    def build_timezone_pairs(self, country_codes):
        if len(country_codes) == 1:
            shortlist = self.build_shortlist_timezone_pairs(country_codes[0])
        else:
            shortlist = []

        longlist = []
        for country_code in country_codes:
            longlist += self.build_longlist_timezone_pairs(country_code, sort=False)
        longlist.sort(key=self.collation_key)

        # There may be duplicate entries in the shortlist and longlist.
        # Basically, the shortlist is most useful when there are non-city
        # timezones that may be more familiar to denizens of that country.
        # Big examples are the US in which people tend to think in terms of
        # Eastern/Mountain/etc.  If we see a match in tz code, prefer the
        # longlist's translation and strip it from the shortlist.
        # longlist tends to be more complete in terms of translation coverage
        # (i.e. libicu is more translated than tzsetup)
        shortcopy = shortlist[:]
        for short_item in shortcopy:
            for long_item in longlist:
                if short_item[1] == long_item[1]:
                    shortlist.remove(short_item)
                    break

        return (shortlist, longlist)

    def build_shortlist_timezone_pairs(self, country_code):
        try:
            shortlist = self.choices_display_map('tzsetup/country/%s' % country_code)
            for pair in shortlist.items():
                # Remove any 'other' entry, we don't need it
                if pair[1] == 'other':
                    del shortlist[pair[0]]
            shortlist = shortlist.items()
            shortlist.sort(key=self.collation_key)
            return shortlist
        except debconf.DebconfError:
            return []

    def get_country_name(self, country):
        # Relatively expensive algorithmically, but we don't call this often.
        try:
            continents = self.choices_untranslated('localechooser/continentlist')
            for continent in continents:
                choices = self.choices_display_map('localechooser/countrylist/%s' % continent.replace(' ', '_'))
                for name, code in choices.items():
                    if code == country:
                        return name
        except debconf.DebconfError, e:
            print "Couldn't get country name for %s: %s" % (country, e)
        return None

    def get_city_name_from_tzdata(self, tz):
        city = tz.split('/', 1)[1]
        # Iterate through tzdata's regions, check each region's tz list for
        # our city.  Like get_country_name, this is inefficient (we could
        # cache this info), but we don't need to run this often.
        try:
            areas = self.choices_untranslated('tzdata/Areas')
            for area in areas:
                zones = self.choices_display_map('tzdata/Zones/%s' % area)
                for name, code in zones.items():
                    if code == city:
                        return name
        except debconf.DebconfError, e:
            print "Couldn't get city name for %s: %s" % (tz, e)
        return None

    def get_fallback_translation_for_tz(self, country, tz):
        # We want to return either 'Country' or 'Country (City)', translated
        # First, get country name.  We need that regardless
        country_name = self.get_country_name(country)
        if country_name is None:
            return None
        show_city = len(self.tzdb.cc_to_locs[country]) > 1
        if show_city:
            # First, try tzdata's translation.
            city_name = self.get_city_name_from_tzdata(tz)
            if city_name is None:
                city_name = tz # fall back to ASCII name
            city_name = city_name.split('/')[-1]
            return "%s (%s)" % (country_name, city_name)
        else:
            return country_name

    # Returns [('translated long list of timezones', 'timezone')...] list
    def build_longlist_timezone_pairs(self, country_code, sort=True):
        if 'LANG' not in os.environ:
            return [] # ?!
        locale = os.environ['LANG'].rsplit('.', 1)[0]
        tz_format = PyICU.SimpleDateFormat('VVVV', PyICU.Locale(locale))
        now = time.time()*1000
        rv = []
        try:
            locs = self.tzdb.cc_to_locs[country_code] # BV failed?
        except:
            # Some countries in tzsetup don't exist in zone.tab...
            # Specifically BV (Bouvet Island) and
            # HM (Heard and McDonald Islands).  Both are uninhabited.
            locs = []
        for location in locs:
            tz_format.setTimeZone(PyICU.TimeZone.createTimeZone(location.zone))
            translated = tz_format.format(now)
            # Check if PyICU had a valid translation for this timezone.  If it
            # doesn't, the returned string will look like GMT+0002 or somesuch.
            # Sometimes the GMT is translated (like in Chinese), so we check
            # for the number part.  PyICU does not indicate a 'translation
            # failure' like this in any way...
            if re.search('.*[-+][0-9][0-9]:?[0-9][0-9]$', translated):
                # Wasn't something that PyICU understood...
                name = self.get_fallback_translation_for_tz(country_code, location.zone)
                rv.append((name, location.zone))
            else:
                rv.append((translated, location.zone))
        if sort:
            rv.sort(key=self.collation_key)
        return rv

    # Returns [('translated long list of timezones', 'timezone')...] list
    def build_longlist_timezone_pairs_by_continent(self, continent):
        if 'LANG' not in os.environ:
            return [] # ?
        rv = []
        try:
            regions = self.choices_untranslated('localechooser/countrylist/%s' % continent)
            for region in regions:
                rv += self.build_longlist_timezone_pairs(region, sort=False)
            rv.sort(key=self.collation_key)
        except debconf.DebconfError:
            pass
        return rv

    def ok_handler(self):
        zone = self.ui.get_timezone()
        if zone is None:
            zone = self.db.get('time/zone')
        else:
            self.preseed('time/zone', zone)
        for location in self.tzdb.locations:
            if location.zone == zone:
                self.preseed('debian-installer/country', location.country)
                break
        Plugin.ok_handler(self)

    def cleanup(self):
        Plugin.cleanup(self)
        i18n.reset_locale(self.frontend, just_country=True)

class Install(InstallPlugin):
    def prepare(self, unfiltered=False):
        tzsetup_script = '/usr/lib/ubiquity/tzsetup/post-base-installer'
        clock_script = '/usr/share/ubiquity/clock-setup-apply'

        if 'UBIQUITY_OEM_USER_CONFIG' in os.environ:
            tzsetup_script += '-oem'

        return (['sh', '-c', '%s && %s' % (tzsetup_script, clock_script)], [])

    def install(self, target, progress, *args, **kwargs):
        progress.info('ubiquity/install/timezone')
        return InstallPlugin.install(self, target, progress, *args, **kwargs)
