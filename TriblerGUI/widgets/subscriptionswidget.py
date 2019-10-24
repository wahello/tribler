from __future__ import absolute_import

from PyQt5.QtCore import pyqtSignal
from PyQt5.QtGui import QIcon, QPixmap
from PyQt5.QtWidgets import QWidget

import Tribler.Core.Utilities.json_util as json

from TriblerGUI.tribler_request_manager import TriblerRequestManager
from TriblerGUI.utilities import format_votes, get_image_path


class SubscriptionsWidget(QWidget):
    """
    This widget shows a favorite button and the number of subscriptions that a specific channel has.
    """

    credit_mining_toggled = pyqtSignal(bool)

    def __init__(self, parent):
        QWidget.__init__(self, parent)

        self.subscribe_button = None
        self.credit_mining_button = None
        self.request_mgr = None
        self.initialized = False
        self.contents_widget = None

    def initialize(self, contents_widget):
        if not self.initialized:
            # We supply a link to the parent channelcontentswidget to use its property that
            # returns the current model in use (top of the stack)
            self.contents_widget = contents_widget
            self.subscribe_button = self.findChild(QWidget, "subscribe_button")
            self.credit_mining_button = self.findChild(QWidget, "credit_mining_button")

            self.subscribe_button.clicked.connect(self.on_subscribe_button_click)
            self.credit_mining_button.clicked.connect(self.on_credit_mining_button_click)
            self.initialized = True

    def update_subscribe_button(self, remote_response=None):
        if remote_response and "subscribed" in remote_response:
            self.contents_widget.model.channel_info["subscribed"] = remote_response["subscribed"]

        color = '#FE6D01' if int(self.contents_widget.model.channel_info["subscribed"]) else '#fff'
        self.subscribe_button.setStyleSheet('border:none; color: %s' % color)
        self.subscribe_button.setText(format_votes(self.contents_widget.model.channel_info['votes']))

        if self.window().tribler_settings:  # It could be that the settings are not loaded yet
            self.credit_mining_button.setHidden(not self.window().tribler_settings["credit_mining"]["enabled"])
            self.credit_mining_button.setIcon(
                QIcon(
                    QPixmap(
                        get_image_path(
                            'credit_mining_yes.png'
                            if self.contents_widget.model.channel_info["public_key"]
                            in self.window().tribler_settings["credit_mining"]["sources"]
                            else 'credit_mining_not.png'
                        )
                    )
                )
            )
        else:
            self.credit_mining_button.hide()

        # Disable channel control buttons for LEGACY_ENTRY channels
        hide_controls = self.contents_widget.model.channel_info["status"] == 1000
        self.subscribe_button.setHidden(hide_controls)
        self.credit_mining_button.setHidden(hide_controls)

    def on_subscribe_button_click(self):
        self.request_mgr = TriblerRequestManager()
        self.request_mgr.perform_request(
            "metadata/%s/%i"
            % (self.contents_widget.model.channel_info[u'public_key'], self.contents_widget.model.channel_info[u'id']),
            lambda data: self.update_subscribe_button(remote_response=data),
            raw_data=json.dumps({"subscribed": int(not self.contents_widget.model.channel_info["subscribed"])}),
            method='PATCH',
        )

    def on_credit_mining_button_click(self):
        old_sources = self.window().tribler_settings["credit_mining"]["sources"]
        new_sources = (
            []
            if self.contents_widget.model.channel_info["public_key"] in old_sources
            else [self.contents_widget.model.channel_info["public_key"]]
        )
        settings = {"credit_mining": {"sources": new_sources}}

        self.request_mgr = TriblerRequestManager()
        self.request_mgr.perform_request(
            "settings", self.on_credit_mining_sources, method='POST', raw_data=json.twisted_dumps(settings)
        .decode('utf-8'))

    def on_credit_mining_sources(self, json_result):
        if not json_result:
            return
        if json_result["modified"]:
            old_source = next(iter(self.window().tribler_settings["credit_mining"]["sources"]), None)
            if self.contents_widget.model.channel_info["public_key"] != old_source:
                self.credit_mining_toggled.emit(True)
                new_sources = [self.contents_widget.model.channel_info["public_key"]]
            else:
                self.credit_mining_toggled.emit(False)
                new_sources = []

            self.window().tribler_settings["credit_mining"]["sources"] = new_sources

            self.update_subscribe_button()
