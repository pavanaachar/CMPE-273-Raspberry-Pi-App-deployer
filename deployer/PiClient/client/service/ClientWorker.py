import os
import json
import logging
import pika
import uuid
from client.common.VirtualEnv import VirtualEnvHandler
from client.common.VirtualEnv import cleanupVirtualEnvHandler
from client.common.GitRepoHandler import gitClone


LOG = logging.getLogger(__name__)


def getPyFile(PyFileDir):
    for pyfile in os.listdir(PyFileDir):
        if pyfile.endswith(".py"):
            return os.path.join(PyFileDir+"/", pyfile)


def work(gitURL):
    venvHdl = VirtualEnvHandler()
    venvDir = venvHdl.getVenvDir()

    repoName = gitURL.split('/')[-1]
    gitRepoDir = venvDir + '/' + repoName
    gitClone(gitRepoDir, gitURL)

    reqFile = gitRepoDir + '/' + 'requirements.txt'

    venvHdl.installReqsInVirtualEnv(reqFile)

    pyFile = getPyFile(gitRepoDir)
    ret = venvHdl.testAppInVirtualEnv(cmdargs=['python', pyFile])

    cleanupVirtualEnvHandler(venvHdl)
    return ret


class RabbitConnection(object):
    def __init__(self, conf):
        rabbit_host = conf.get('rabbit', 'host')
        rabbit_user = conf.get('rabbit', 'username')
        rabbit_pass = conf.get('rabbit', 'password')
        rabbit_port = conf.getint('rabbit', 'port') if conf.has_option('rabbit', 'port') else 5672
        self.my_ip = conf.get('DEFAULT', 'ip')
        credentials = pika.PlainCredentials(rabbit_user, rabbit_pass)
        self.rabbit_conn = pika.BlockingConnection(
                pika.ConnectionParameters(rabbit_host,
                                          rabbit_port, '/',
                                          credentials))
        self.rabbit_channel = self.rabbit_conn.channel()
        queue = self.rabbit_channel.queue_declare(exclusive=True)
        self.callback_queue = queue.method.queue
        self.rabbit_channel.basic_consume(self.on_register, no_ack=True, queue=self.callback_queue)
        self.pi_registered = False

    def call_register(self):
        self.corr_id = str(uuid.uuid4())
        self.rabbit_channel.basic_publish(exchange='',
                                          routing_key='register_pi',
                                          properties=pika.BasicProperties(
                                              reply_to=self.callback_queue,
                                              correlation_id=self.corr_id),
                                          body=str(self.my_ip))
        while not self.pi_registered:
            self.rabbit_conn.process_data_events()
        LOG.info('Registration successful')

    def OnDeployRequest(self, ch, method, props, body):
#        deploySuccess = work(body)
        LOG.info('Processing %s' % body)
        deploySuccess = True
        if deploySuccess:
            response = json.dumps({'status': True,
             'message': '__placeholder'})
        else:
            response = json.dumps({'status': False,
             'message': '__placeholder'})
        ch.basic_publish(exchange='',
                         routing_key=props.reply_to,
                         properties=pika.BasicProperties(
                             correlation_id = props.correlation_id,
                         ),
                         body=response)
        ch.basic_ack(delivery_tag=method.delivery_tag)

    def on_register(self, ch, method, props, body):
        if self.corr_id == props.correlation_id:
            LOG.info('Registered self with %s' % self.my_ip)
            self.pi_registered = True

    def start(self):
        self.call_register()
        self.rabbit_channel.basic_consume(self.OnDeployRequest, queue=self.my_ip)
        LOG.info('Starting rabbit listener...')
        self.rabbit_channel.start_consuming()

def start_service(config):
    rclient = RabbitConnection(config)
    rclient.start()
    LOG.error('Something went wrong. Rabbit listener exited')
