# coding: utf-8
from datetime import datetime
import os
import ssl
import requests
from requests.adapters import HTTPAdapter
from requests.packages.urllib3.poolmanager import PoolManager
import xml.dom.minidom
from decimal import Decimal
from util import moneyfmt


VISA, MASTERCARD, DINERS, DISCOVER, ELO, AMEX = 'visa', \
    'mastercard', 'diners', 'discover', 'elo', 'amex'
CARD_TYPE_C = (
    (VISA, u'Visa'),
    (MASTERCARD, u'Mastercard'),
    (DINERS, u'Diners'),
    (DISCOVER, u'Discover'),
    (ELO, u'ELO'),
    (AMEX, u'American express'),
)

CASH, INSTALLMENT_STORE, INSTALLMENT_CIELO, DEBT = 1, 2, 3, 'A'
TRANSACTION_TYPE_C = (
    (CASH, u'À vista'),
    (INSTALLMENT_STORE, u'Parcelado (estabelecimento)'),
    (INSTALLMENT_CIELO, u'Parcelado (Cielo)'),
    (DEBT, u'Débito em conta'),
)

SANDBOX_URL = 'https://qasecommerce.cielo.com.br/servicos/ecommwsec.do'
PRODUCTION_URL = 'https://ecommerce.cbmp.com.br/servicos/ecommwsec.do'
CIELO_MSG_ERRORS = {
    '001': u'A mensagem XML está fora do formato especificado pelo arquivo ecommerce.xsd (001-Mensagem inválida)',
    '002': u'Impossibilidade de autenticar uma requisição da loja virtual. (002-Credenciais inválidas)',
    '003': u'Não existe transação para o identificador informado. (003-Transação inexistente)',
    '010': u'A transação, com ou sem cartão, está divergente com a permissão do envio dessa informação. (010-Inconsistência no envio do cartão)',
    '011': u'A transação está configurada com uma modalidade de pagamento não habilitada para a loja. (011-Modalidade não habilitada)',
    '012': u'O número de parcelas solicitado ultrapassa o máximo permitido. (012-Número de parcelas inválido)',
    '013': u'Flag de autorizacao automatica invalida',
    '014': u'Autorizacao Direta inválida',
    '015': u'A solicitação de Autorização Direta está sem cartão',
    '016': u'O TID fornecido está duplicado',
    '017': u'Cádigo de segurança ausente',
    '018': u'Indicador de cádigo de segurança inconsistente',
    '019': u'A URL de Retorno é obrigatória, exceto para recorrência e autorização direta.',
    '020': u'Não é permitido realizar autorização para o status da transação. (020-Status não permite autorização)',
    '021': u'Não é permitido realizar autorização, pois o prazo está vencido. (021-Prazo de autorização vencido)',
    '022': u'EC não possui permissão para realizar a autorização.(022-EC não autorizado)',
    '025': u'Encaminhamento a autorização não permitido',
    '030': u'A captura não pode ser realizada, pois a transação não está autorizada.(030-Transação não autorizada para captura)',
    '031': u'A captura não pode ser realizada, pois o prazo para captura está vencido.(031-Prazo de captura vencido)',
    '032': u'O valor solicitado para captura não é válido.(032-Valor de captura inválido)',
    '033': u'Não foi possível realizar a captura.(033-Falha ao capturar)',
    '034': u'Valor da taxa de embarque obrigatório',
    '035': u'A bandeira utilizada na transação não tem suporte à Taxa de Embarque',
    '036': u'Produto inválido para utilização da Taxa de Embarque',
    '040': u'O cancelamento não pode ser realizado, pois o prazo está vencido.(040-Prazo de cancelamento vencido)',
    '041': u'O atual status da transação não permite cancelament.(041-Status não permite cancelamento)',
    '042': u'Não foi possível realizar o cancelamento.(042-Falha ao cancelar)',
    '043': u'O valor que está tentando cancelar supera o valor total capturado da transacao.',
    '044': u'Para cancelar ou capturar essa transação, envie um e-mail para o Suporte Web Cielo eCommerce (cieloecommerce@cielo.com.br)',
    '051': u'Recorrência Inválida',
    '052': u'Token Inválido',
    '053': u'Recorrência não habilitada',
    '054': u'Transacao com Token invalida',
    '097': u'Sistema indisponivel',
    '098': u'Timeout',
    '099': u'Falha no sistema.(099-Erro inesperado)',
}

# try:
#     SSL_VERSION = ssl.PROTOCOL_SSLv23
# except:
#     SSL_VERSION = ssl.PROTOCOL_TLSv1
#SSL_VERSION = ssl.PROTOCOL_TLSv1
SSL_VERSION = ssl.PROTOCOL_TLSv1_2


class CieloHTTPSAdapter(HTTPAdapter):
    def init_poolmanager(self, connections, maxsize, **kwargs):
        self.poolmanager = PoolManager(
            num_pools=connections,
            maxsize=maxsize,
            ssl_version=SSL_VERSION,
            **kwargs)


class CieloSkipAdapter(HTTPAdapter):
    def init_poolmanager(self, connections, maxsize, block=False):
        self.poolmanager = PoolManager(
            num_pools=connections,
            maxsize=maxsize,
            block=block,
            assert_hostname=False)


class GetAuthorizedException(Exception):
    def __init__(self, id, message=None):
        self.id = id
        self.message = message

    def __str__(self):
        return u'%s - %s' % (self.id, self.message)


class CaptureException(Exception):
    pass


class TokenException(Exception):
    pass


class BaseCieloObject(object):
    template = ''

    def __init__(self, sandbox=False, use_ssl=None):
        self.session = requests.Session()

        if use_ssl is None:
            use_ssl = not sandbox

        if use_ssl and sandbox:
            self.session.mount('http://', CieloSkipAdapter())

        if use_ssl and not sandbox:
            self.session.mount('https://', CieloHTTPSAdapter())

    def get_xml_transaction_id(self):
        import uuid
        return str(uuid.uuid4())

    def create_token(self):
        self.payload = open(
            os.path.join(
                os.path.dirname(os.path.abspath(__file__)),
                self.template), 'r').read() % self.__dict__
        self.response = self.session.post(
            self.url,
            data={'mensagem': self.payload, })

        self.dom = xml.dom.minidom.parseString(self.response.content)

        if self.dom.getElementsByTagName('erro'):
            raise TokenException('Erro ao gerar token!')

        self.token = self.dom.getElementsByTagName(
            'codigo-token')[0].childNodes[0].data
        self.status = self.dom.getElementsByTagName(
            'status')[0].childNodes[0].data
        self.card = self.dom.getElementsByTagName(
            'numero-cartao-truncado')[0].childNodes[0].data
        return True

    def capture(self):
        assert self._authorized, \
            u'get_authorized(...) must be called before capture(...)'

        payload = open(
            os.path.join(
                os.path.dirname(os.path.abspath(__file__)),
                'templates/capture.xml'),
            'r').read() % self.__dict__

        response = self.session.post(self.url, data={
            'mensagem': payload,
        })

        dom = xml.dom.minidom.parseString(response.content)
        status = int(dom.getElementsByTagName('status')[0].childNodes[0].data)

        if status != 6:
            # 6 = capturado
            raise CaptureException()
        return True

    def consult(self, **kwargs):
        self.date = datetime.now().strftime('%Y-%m-%dT%H:%M:%S')
        self.payload = open(
            os.path.join(
                os.path.dirname(os.path.abspath(__file__)), self.template),
            'r').read() % self.__dict__
        self.response = self.session.post(
            self.url,
            data={'mensagem': self.payload, })
        self.content = self.response.content
        self.dom = xml.dom.minidom.parseString(self.content)

    def assert_transaction_is_paid(self):
        self.consult()
        self.status = int(
            self.dom.getElementsByTagName('status')[0].childNodes[0].data)
        if self.status in [2, 4, 6]:
            if self.status != 6:
                self.capture()
            return True
        return False

    def assert_transaction_value(self, value):
        self.consult()
        try:
            transaction_value = self.dom.getElementsByTagName(
                'valor')[0].childNodes[0].data
            return int(transaction_value) >= int(moneyfmt(
                value, sep='', dp=''))
        except Exception:
            return False

    def cancel(self, **kwargs):

        self.date = datetime.now().strftime('%Y-%m-%dT%H:%M:%S')
        self.payload = open(
            os.path.join(
                os.path.dirname(os.path.abspath(__file__)), self.template),
            'r').read() % self.__dict__
        self.response = self.session.post(
            self.url,
            data={'mensagem': self.payload, })
        self.content = self.response.content
        self.dom = xml.dom.minidom.parseString(self.content)

        if self.dom.getElementsByTagName('erro'):
            self.error = self.dom.getElementsByTagName(
                'erro')[0].getElementsByTagName('codigo')[0].childNodes[0].data
            self.error_id = None
            self.error_message = CIELO_MSG_ERRORS.get(self.error, u'Erro não catalogado')
            raise GetAuthorizedException(self.error_id, self.error_message)

        self.status = int(
            self.dom.getElementsByTagName('status')[0].childNodes[0].data)

        if self.status in [9, 12]:
            self.canceled = True
            return True

        if 'Cancelamento parcial realizado com sucesso' in self.response.content:
            return True

        return False

    def get_authorized(self):
        self.date = datetime.now().strftime('%Y-%m-%dT%H:%M:%S')
        self.payload = open(
            os.path.join(
                os.path.dirname(os.path.abspath(__file__)),
                self.template),
            'r').read() % self.__dict__

        self.response = self.session.post(
            self.url,
            data={'mensagem': self.payload, })

        self.dom = xml.dom.minidom.parseString(self.response.content)

        if self.dom.getElementsByTagName('erro'):
            self.error = self.dom.getElementsByTagName(
                'erro')[0].getElementsByTagName('codigo')[0].childNodes[0].data
            self.error_id = None
            self.error_message = CIELO_MSG_ERRORS.get(self.error, u'Erro não catalogado')
            raise GetAuthorizedException(self.error_id, self.error_message)

        self.status = int(self.dom.getElementsByTagName('status')[0].childNodes[0].data)

        if self.status != 4:
            self.error_id = self.dom.getElementsByTagName(
                'autorizacao')[0].getElementsByTagName(
                    'codigo')[0].childNodes[0].data
            self.error_message = self.dom.getElementsByTagName(
                'autorizacao')[0].getElementsByTagName(
                    'mensagem')[0].childNodes[0].data
            self._authorized = False
            raise GetAuthorizedException(self.error_id, self.error_message)

        self.transaction_id = self.dom.getElementsByTagName('tid')[0].childNodes[0].data
        try:
            self.pan = self.dom.getElementsByTagName('pan')[0].childNodes[0].data
        except:
            self.pan = ''

        self._authorized = True
        return True

    def get_token(self):
        try:
            self.token = self.dom.getElementsByTagName('codigo-token')[0].childNodes[0].data
            self.status = self.dom.getElementsByTagName('status')[0].childNodes[0].data
            self.card = self.dom.getElementsByTagName('numero-cartao-truncado')[0].childNodes[0].data
            return self.token
        except:
            self.token = None
            self.status = None
            self.card = None
        return False


class CaptureTransaction(BaseCieloObject):
    template = 'templates/capture.xml'

    def __init__(
            self,
            affiliation_id,
            api_key,
            transaction_id,
            sandbox=False,
            use_ssl=None, ):
        super(CaptureTransaction, self).__init__(sandbox=sandbox, use_ssl=use_ssl)
        self.url = SANDBOX_URL if sandbox else PRODUCTION_URL
        self.affiliation_id = affiliation_id
        self.api_key = api_key
        self.transaction_id = transaction_id
        self.sandbox = sandbox
        self._authorized = True


class CieloToken(BaseCieloObject):
    template = 'templates/token.xml'

    def __init__(
            self,
            affiliation_id,
            api_key,
            card_type,
            card_number,
            exp_month,
            exp_year,
            card_holders_name,
            sandbox=False,
            use_ssl=None,
        ):
        super(CieloToken, self).__init__(sandbox=sandbox, use_ssl=use_ssl)

        if len(str(exp_year)) == 2:
            exp_year = '20%s' % exp_year

        if len(str(exp_month)) == 1:
            exp_month = '0%s' % exp_month

        self.url = SANDBOX_URL if sandbox else PRODUCTION_URL
        self.card_type = card_type
        self.affiliation_id = affiliation_id
        self.api_key = api_key
        self.exp_month = exp_month
        self.exp_year = exp_year
        self.expiration = '%s%s' % (exp_year, exp_month)
        self.card_holders_name = card_holders_name
        self.card_number = card_number
        self.sandbox = sandbox


class ConsultTransaction(BaseCieloObject):
    template = 'templates/consult.xml'

    def __init__(
            self,
            affiliation_id,
            api_key,
            transaction_id,
            sandbox=False,
            use_ssl=None,
        ):
        super(ConsultTransaction, self).__init__(sandbox=sandbox, use_ssl=use_ssl)
        self.url = SANDBOX_URL if sandbox else PRODUCTION_URL
        self.affiliation_id = affiliation_id
        self.api_key = api_key
        self.transaction_id = transaction_id


class CancelTransaction(BaseCieloObject):
    template = 'templates/cancel.xml'

    def __init__(
            self,
            affiliation_id,
            api_key,
            transaction_id,
            amount_to_cancel=None,
            sandbox=False,
            use_ssl=None,
        ):
        super(CancelTransaction, self).__init__(sandbox=sandbox, use_ssl=use_ssl)
        self.url = SANDBOX_URL if sandbox else PRODUCTION_URL
        self.affiliation_id = affiliation_id
        self.api_key = api_key
        self.transaction_id = transaction_id
        self.sandbox = sandbox
        self.xml_transaction_id = self.get_xml_transaction_id()

        self.template = 'templates/cancel.xml'
        if amount_to_cancel:
            assert isinstance(amount_to_cancel, Decimal), u'amount must be an instance of Decimal'
            self.amount_to_cancel = moneyfmt(amount_to_cancel, sep='', dp='')
            self.template = 'templates/cancel_with_amount.xml'


class TokenPaymentAttempt(BaseCieloObject):
    template = 'templates/authorize_token.xml'

    def __init__(
            self,
            affiliation_id,
            token,
            api_key,
            total,
            card_type,
            order_id,
            url_redirect,
            installments=1,
            transaction=CASH,
            sandbox=False,
            use_ssl=None,
            authorize=3,
        ):
        super(TokenPaymentAttempt, self).__init__(sandbox=sandbox, use_ssl=use_ssl)
        assert isinstance(total, Decimal), u'total must be an instance of Decimal'
        assert installments in range(1, 13), u'installments must be a integer between 1 and 12'

        assert (installments == 1 and transaction == CASH) \
                    or installments > 1 and transaction != CASH, \
                    u'if installments = 1 then transaction must be None or "cash"'

        self.url = SANDBOX_URL if sandbox else PRODUCTION_URL
        self.card_type = card_type
        self.token = token
        self.affiliation_id = affiliation_id
        self.api_key = api_key
        self.transaction = transaction
        self.transaction_type = transaction  # para manter assinatura do pyrcws
        self.total = moneyfmt(total, sep='', dp='')
        self.installments = installments
        self.order_id = order_id
        self._authorized = False
        self.sandbox = sandbox
        self.url_redirect = url_redirect
        self.authorize = authorize


class PaymentAttempt(BaseCieloObject):
    template = 'templates/authorize.xml'

    def __init__(
            self,
            affiliation_id,
            api_key,
            total,
            card_type,
            installments,
            order_id,
            card_number,
            cvc2,
            exp_month,
            exp_year,
            card_holders_name,
            transaction=CASH,
            sandbox=False,
            use_ssl=None,
        ):

        super(PaymentAttempt, self).__init__(sandbox=sandbox, use_ssl=use_ssl)
        assert isinstance(total, Decimal), u'total must be an instance of Decimal'
        assert installments in range(1, 13), u'installments must be a integer between 1 and 12'

        assert (installments == 1 and transaction == CASH) \
                    or installments > 1 and transaction != CASH, \
                    u'if installments = 1 then transaction must be None or "cash"'

        if len(str(exp_year)) == 2:
            exp_year = '20%s' % exp_year  # FIXME: bug do milênio em 2100

        self.url = SANDBOX_URL if sandbox else PRODUCTION_URL
        self.card_type = card_type
        self.affiliation_id = affiliation_id
        self.api_key = api_key
        self.transaction = transaction
        self.transaction_type = transaction  # para manter assinatura do pyrcws
        self.total = moneyfmt(total, sep='', dp='')
        self.installments = installments
        self.order_id = order_id
        self.card_number = card_number
        self.cvc2 = cvc2
        self.exp_month = exp_month
        self.exp_year = exp_year
        self.expiration = '%s%s' % (exp_year, exp_month)
        self.card_holders_name = card_holders_name
        self._authorized = False
        self.sandbox = sandbox


class UpdatePaymentAttempt(BaseCieloObject):
    template = 'templates/authorize_update.xml'

    def __init__(
            self,
            affiliation_id,
            api_key,
            total,
            card_type,
            installments,
            order_id,
            card_number,
            cvc2,
            exp_month,
            exp_year,
            card_holders_name,
            transaction=CASH,
            sandbox=False,
            use_ssl=None,
            gerar_token=False,
        ):

        super(UpdatePaymentAttempt, self).__init__(sandbox=sandbox, use_ssl=use_ssl)
        assert isinstance(total, Decimal), u'total must be an instance of Decimal'
        assert installments in range(1, 13), u'installments must be a integer between 1 and 12'
        assert (installments == 1 and transaction == CASH) or installments > 1 and transaction != CASH, u'if installments = 1 then transaction must be None or "cash"'

        if len(str(exp_year)) == 2:
            exp_year = '20%s' % exp_year  # FIXME: bug do milênio em 2100

        self.url = SANDBOX_URL if sandbox else PRODUCTION_URL
        self.card_type = card_type
        self.affiliation_id = affiliation_id
        self.api_key = api_key
        self.transaction = transaction
        self.transaction_type = transaction  # para manter assinatura do pyrcws
        self.total = moneyfmt(total, sep='', dp='')
        self.installments = installments
        self.order_id = order_id
        self.card_number = card_number
        self.cvc2 = cvc2
        self.exp_month = exp_month
        self.exp_year = exp_year
        self.expiration = '%s%s' % (exp_year, exp_month)
        self.card_holders_name = card_holders_name
        self._authorized = False
        self.sandbox = sandbox
        self.gerar_token = 'true' if gerar_token else 'false'
        self.xml_transaction_id = self.get_xml_transaction_id()


class DebtAttempt(BaseCieloObject):
    template = 'templates/authorize_debt.xml'

    def __init__(
            self,
            affiliation_id,
            api_key,
            total,
            card_type,
            order_id,
            card_number,
            cvc2,
            exp_month,
            exp_year,
            card_holders_name,
            url_redirect,
            sandbox=False,
            use_ssl=None,
        ):
        super(DebtAttempt, self).__init__(sandbox=sandbox, use_ssl=use_ssl)
        assert isinstance(total, Decimal), u'total must be an instance of Decimal'

        if len(str(exp_year)) == 2:
            exp_year = '20%s' % exp_year

        self.url_redirect = url_redirect
        self.url = SANDBOX_URL if sandbox else PRODUCTION_URL
        self.card_type = card_type
        self.affiliation_id = affiliation_id
        self.api_key = api_key
        self.total = moneyfmt(total, sep='', dp='')
        self.order_id = order_id
        self.card_number = card_number
        self.cvc2 = cvc2
        self.exp_month = exp_month
        self.exp_year = exp_year
        self.expiration = '%s%s' % (exp_year, exp_month)
        self.card_holders_name = card_holders_name
        self._authorized = False

        self.sandbox = sandbox

    def get_authorized(self):
        self.date = datetime.now().strftime('%Y-%m-%dT%H:%M:%S')
        self.payload = open(
            os.path.join(
                os.path.dirname(os.path.abspath(__file__)),
                self.template),
            'r').read() % self.__dict__

        self.response = self.session.post(
            self.url,
            data={'mensagem': self.payload, })

        self.dom = xml.dom.minidom.parseString(self.response.content)

        if self.dom.getElementsByTagName('erro'):
            self.error = self.dom.getElementsByTagName(
                'erro')[0].getElementsByTagName('codigo')[0].childNodes[0].data
            self.error_id = None
            self.error_message = CIELO_MSG_ERRORS.get(self.error, u'Erro não catalogado')
            raise GetAuthorizedException(self.error_id, self.error_message)

        self.url_autenticacao = self.dom.getElementsByTagName('url-autenticacao')[0].childNodes[0].data
        return True
