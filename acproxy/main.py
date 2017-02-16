#!/usr/bin/env python

# Gmail settings:
#
# IMAP
# - host: imap.googlemail.com
# - port: 997
# - security: TLS/SSL
#
# SMTP
#
# - host: smtp.googlemail.com
# - port: 465
# - connection: SSL/TLS


import sys


from twisted.internet import protocol, reactor, ssl
from twisted.python import log
from twisted.internet.protocol import ServerFactory, ClientFactory


class SmtpServerConnector():
    def connect(self, factory):
        raise NotImplementedError()


class SmtpOverTls(SmtpServerConnector):
    def __init__(self, host, port):
        self.host = host
        self.port = port

    def connect(self, factory):
        return reactor.connectSSL(
             self.host, self.port, factory, ssl.ClientContextFactory()
        )


class SmtpOverPlaintext(SmtpServerConnector):
    def __init__(self, host, port):
        self.host = host
        self.port = port

    def connect(self, factory):
        return reactor.connectTCP(self.host, self.port, factory)


class OppositeConnectionMixin():
    def set_opposite_connection(self, connection):
        self.__opposite_connection = connection

    @property
    def opposite_connection(self):
        try:
            return self.__opposite_connection
        except AttributeError:
            raise RuntimeError("Don't have an opposite connection yet.")


class InboundSmtpConnection(protocol.Protocol, OppositeConnectionMixin):
    """
    This class represents an inbound connection to the proxy, e.g. a mail
    client has connected.

    We subsequently open a connection to the *real* SMTP server and funnel
    data between the two.
    """

    def set_outbound_smtp_connector(self, outbound_smtp_connector):
        self.outbound_smtp_connector = outbound_smtp_connector

    def connectionMade(self):
        log.msg("Got inbound connection, connecting to remote SMTP server.")

        # don't pass data until the remote server has connected
        self.transport.pauseProducing()

        self.outbound_smtp_connector.connect(MyClientFactory(self))

    def dataReceived(self, data):
        log.msg("dataReceived user -> proxy: `{}`".format(
            data.decode('utf-8').rstrip('\r\n')))

        self.opposite_connection.transport.write(data)

    def connectionLost(self, reason):
        log.msg("Connection lost with inbound client")
        self.opposite_connection.transport.loseConnection()

    def set_opposite_connection(self, *args, **kwargs):
        super(InboundSmtpConnection, self).set_opposite_connection(
            *args, **kwargs)
        self.transport.resumeProducing()  # now we can accept data


class OutboundSmtpConnection(protocol.Protocol, OppositeConnectionMixin):

    def connectionMade(self):
        log.msg("connectionMade to remote SMTP server")

        # Tell the other side about ourself
        self.opposite_connection.set_opposite_connection(self)

    def dataReceived(self, data):
        log.msg("dataReceived proxy <= SMTP: `{}`".format(
            data.decode('utf-8').rstrip('\r\n')))
        self.opposite_connection.transport.write(data)

    def connectionLost(self, reason):
        log.msg("Connection lost to remote SMTP server")
        self.opposite_connection.transport.loseConnection()


class MyServerFactory(ServerFactory):
    protocol = InboundSmtpConnection

    def __init__(self, outbound_smtp_connector):
        self.outbound_smtp_connector = outbound_smtp_connector

    def buildProtocol(self, addr):
        inbound_smtp_connection = ServerFactory.buildProtocol(self, addr)

        inbound_smtp_connection.set_outbound_smtp_connector(
            self.outbound_smtp_connector
        )

        return inbound_smtp_connection


class MyClientFactory(ClientFactory):
    protocol = OutboundSmtpConnection

    def __init__(self, inbound_smtp_connection):
        self.inbound_smtp_connection = inbound_smtp_connection

    def buildProtocol(self, addr):
        outbound_smtp = ClientFactory.buildProtocol(self, addr)
        outbound_smtp.set_opposite_connection(self.inbound_smtp_connection)

        return outbound_smtp


def main():
    log.startLogging(sys.stdout)

    google_smtp = SmtpOverTls('smtp.googlemail.com', 465)
    # google_smtp = SmtpOverPlaintext('smtp.googlemail.com', 25)

    reactor.listenTCP(2525, MyServerFactory(google_smtp))
    reactor.run()

if __name__ == '__main__':
    main()
